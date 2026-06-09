"""
LiveKit Agent worker — Gemini LLM · Deepgram STT · Deepgram TTS

Stack:
  STT  — Deepgram nova-2-phonecall  (streaming, phone-optimised)
  LLM  — Gemini 2.5 Flash           (streaming, low first-token latency)
  TTS  — Deepgram Aura aura-orion   (streaming chunks, no buffering)
  VAD  — Silero                     (very low threshold for SIP/G.711 audio)

Call flow:
  1. Agent connects to LiveKit room
  2. Session is started (registers audio listeners)
  3. Outbound SIP call is placed — blocks until customer answers
  4. Agent greets based on persona (no hardcoded script)
  5. Real-time conversation until participant disconnects
  6. Post-call: Gemini extracts lead data → stored to disk
"""

import asyncio
import json
import time
from datetime import datetime, timezone

from livekit import api
from livekit.agents import AgentServer, AgentSession, AutoSubscribe, JobContext, JobExecutorType, RoomInputOptions
from livekit.agents import ConversationItemAddedEvent, UserInputTranscribedEvent, AgentStateChangedEvent
from livekit.agents.llm import ChatMessage
from livekit.agents.voice.turn import TurnHandlingOptions
from livekit.plugins import deepgram, silero
from livekit.plugins import google as lk_google

from app.agents.worker_agent.agent import RealEstateAgent
from app.core.config import SETTINGS
from app.core.constants import AGENT_NAME
from app.core.logging import LOGGER
from app.services.lead_extractor import extract_lead_from_transcript, summarize_transcript
from app.services.storage_service import save_call_record, save_call_history, upsert_lead
from app.websocket.connection_manager import CONNECTION_MANAGER

# SIP customer participant identity — must match create_sip_participant below.
SIP_PARTICIPANT_IDENTITY = "sip-customer"


async def prewarm(proc) -> None:
    silero.VAD.load()


async def entrypoint(ctx: JobContext) -> None:
    # IMPORTANT: auto_subscribe expects an AutoSubscribe enum, NOT a bool.
    # Passing `True` makes `True == AutoSubscribe.SUBSCRIBE_ALL` evaluate False,
    # which silently DISABLES track subscription — the agent then never receives
    # the customer's audio, so STT produces nothing. This was the root cause of
    # "agent never responds to user speech". SUBSCRIBE_ALL subscribes the SIP
    # audio track so STT actually gets frames.
    await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_ALL)

    metadata: dict = {}
    try:
        metadata = json.loads(ctx.job.metadata or ctx.room.metadata or "{}")
    except Exception:
        pass

    call_id: str = metadata.get("call_id", ctx.room.name)
    phone: str   = metadata.get("phone", "unknown")
    start_time   = time.time()
    start_iso    = datetime.now(timezone.utc).isoformat()

    LOGGER.info(f"[{call_id}] Agent entrypoint — room: {ctx.room.name}, phone: {phone}")

    transcript: list[dict] = []
    # Mutable end-state captured by the shutdown handler. "completed" once the
    # customer actually answered; stays "failed"/"no_answer" otherwise.
    call_state = {"status": "no_answer", "answered": False}

    # ── Audio input diagnostics ─────────────────────────────────────────────────
    # The #1 historical bug was customer audio never reaching STT. Log every track
    # subscription and participant join so a single live call is conclusive.
    @ctx.room.on("track_subscribed")
    def _on_track_subscribed(track, publication, participant) -> None:  # noqa: ANN001
        # source must be SOURCE_MICROPHONE for RoomIO to feed it to STT.
        try:
            from livekit import rtc
            source = rtc.TrackSource.Name(publication.source)
        except Exception:
            source = str(getattr(publication, "source", "?"))
        LOGGER.info(
            f"[{call_id}] track_subscribed — kind={track.kind} source={source} "
            f"identity={participant.identity} sid={getattr(publication, 'sid', '?')}"
        )

    @ctx.room.on("participant_connected")
    def _on_participant_connected(participant) -> None:  # noqa: ANN001
        LOGGER.info(
            f"[{call_id}] participant_connected — identity={participant.identity} "
            f"kind={participant.kind}"
        )

    # ── Session ────────────────────────────────────────────────────────────────
    session = AgentSession(
        vad=silero.VAD.load(
            # SIP/G.711 audio has codec noise. Thresholds of 0.05/0.04 treated
            # all noise as speech, so END_OF_SPEECH never fired and STT got no
            # complete utterances. Use sane thresholds with clear hysteresis.
            activation_threshold=0.35,
            deactivation_threshold=0.25,
            min_silence_duration=0.4,
            min_speech_duration=0.05,
            prefix_padding_duration=0.3,
        ),
        stt=deepgram.STT(
            api_key=SETTINGS.DEEPGRAM_API_KEY,
            model="nova-2-phonecall",
            smart_format=True,
            no_delay=True,
            language="en-US",
            endpointing_ms=300,   # 300ms: natural pause time for Indian-accented phone calls
            interim_results=True,
            punctuate=True,       # improves turn detector accuracy
            filler_words=True,    # captures "um"/"uh" and Hinglish fillers
            vad_events=True,      # ensures SpeechStarted events fire
        ),
        llm=lk_google.LLM(
            api_key=SETTINGS.GEMINI_API_KEY,
            model="gemini-2.5-flash",
        ),
        tts=deepgram.TTS(
            api_key=SETTINGS.DEEPGRAM_API_KEY,
            # Streams chunks as soon as they arrive — no full-synthesis wait
            model="aura-orion-en",
        ),
        turn_handling=TurnHandlingOptions(
            # Agent starts responding 100ms after speech ends
            endpointing={"mode": "fixed", "min_delay": 0.1, "max_delay": 1.0},
            # Allow user to interrupt agent mid-sentence naturally
            interruption={"enabled": True, "mode": "vad", "min_duration": 0.2},
        ),
        aec_warmup_duration=0.0,  # No acoustic echo on phone calls
        user_away_timeout=45.0,
        userdata={
            "call_id": call_id,
            "phone":   phone,
            "lead_data": {},
        },
    )

    LOGGER.info(
        f"[{call_id}] Session config — "
        f"STT: nova-2-phonecall endpointing=300ms, "
        f"VAD: activation=0.35 deactivation=0.25 min_silence=0.4s"
    )

    # ── Event hooks ────────────────────────────────────────────────────────────

    @session.on("user_input_transcribed")
    def on_user_transcript(event: UserInputTranscribedEvent) -> None:
        # Logged at INFO (not debug) so the very first event proves STT is
        # receiving customer audio. Empty/interim events are logged too.
        LOGGER.info(
            f"[{call_id}] STT event — final={event.is_final}, "
            f"len={len(event.transcript or '')}"
        )
        text = (event.transcript or "").strip()
        if not text:
            return
        LOGGER.info(f"[{call_id}] STT {'FINAL' if event.is_final else 'interim'}: {text!r}")
        if event.is_final:
            transcript.append({"role": "user", "text": text})
        CONNECTION_MANAGER.broadcast_from_thread(call_id, {
            "type":     "transcript",
            "role":     "user",
            "text":     text,
            "is_final": event.is_final,
            "call_id":  call_id,
        })

    @session.on("conversation_item_added")
    def on_conversation_item(event: ConversationItemAddedEvent) -> None:
        if not isinstance(event.item, ChatMessage) or event.item.role != "assistant":
            return
        text = ""
        for block in (event.item.content or []):
            if isinstance(block, str):
                text += block
            elif hasattr(block, "text") and isinstance(getattr(block, "text"), str):
                text += block.text
        text = text.strip()
        if not text:
            return
        LOGGER.info(f"[{call_id}] AGENT: {text[:120]!r}")
        transcript.append({"role": "agent", "text": text})
        CONNECTION_MANAGER.broadcast_from_thread(call_id, {
            "type":     "transcript",
            "role":     "agent",
            "text":     text,
            "is_final": True,
            "call_id":  call_id,
        })

    @session.on("agent_state_changed")
    def on_state_changed(event: AgentStateChangedEvent) -> None:
        state_str = str(event.new_state).lower()
        LOGGER.info(f"[{call_id}] State → {state_str}")
        ui_state = {"thinking": "thinking", "speaking": "speaking",
                    "listening": "listening", "idle": "idle",
                    "initializing": "idle"}.get(state_str, "idle")
        CONNECTION_MANAGER.broadcast_from_thread(call_id, {
            "type":    "agent_state",
            "call_id": call_id,
            "state":   ui_state,
        })

    # ── Shutdown / post-call cleanup ───────────────────────────────────────────

    async def _on_shutdown() -> None:
        duration_s = int(time.time() - start_time)
        end_iso = datetime.now(timezone.utc).isoformat()
        status = "completed" if call_state["answered"] else call_state["status"]
        LOGGER.info(f"[{call_id}] Shutdown — {duration_s}s, {len(transcript)} turns, status={status}")

        lead = None
        summary = ""
        lead_dict: dict = {}
        try:
            lead = await extract_lead_from_transcript(transcript)
            tool_data = session.userdata.get("lead_data", {})
            for k, v in tool_data.items():
                if v is not None and getattr(lead, k, None) is None:
                    try:
                        setattr(lead, k, v)
                    except Exception:
                        pass
            lead_dict = lead.model_dump(exclude_none=True)

            # Short conversation summary for the call-history record.
            summary = await summarize_transcript(transcript)

            await save_call_record(call_id, phone, transcript, duration_s, lead)
            await upsert_lead(call_id, phone, lead, duration_s)
            await save_call_history({
                "call_id":          call_id,
                "phone":            phone,
                "start_time":       start_iso,
                "end_time":         end_iso,
                "duration_seconds": duration_s,
                "status":           status,
                "transcript":       transcript,
                "summary":          summary,
                "lead_data":        lead_dict,
            })
        except Exception as e:
            LOGGER.error(f"[{call_id}] Post-call error: {e}")
            # Best-effort history persistence even if lead extraction/summary failed.
            try:
                await save_call_history({
                    "call_id":          call_id,
                    "phone":            phone,
                    "start_time":       start_iso,
                    "end_time":         end_iso,
                    "duration_seconds": duration_s,
                    "status":           status,
                    "transcript":       transcript,
                    "summary":          summary,
                    "lead_data":        lead_dict,
                })
            except Exception as e2:
                LOGGER.error(f"[{call_id}] History persist failed: {e2}")
        finally:
            # Always notify the frontend and clear server-side tracking, even if
            # post-call processing raised above.
            try:
                from app.api.call import ACTIVE_CALLS
                ACTIVE_CALLS.pop(call_id, None)
            except Exception:
                pass
            CONNECTION_MANAGER.broadcast_from_thread(call_id, {
                "type":             "call_ended",
                "call_id":          call_id,
                "duration_seconds": duration_s,
                "lead_data":        lead_dict,
            })

    ctx.add_shutdown_callback(_on_shutdown)

    # ── Start session BEFORE placing call ──────────────────────────────────────
    # session.start() registers the participant_connected listener. It must run
    # before the SIP participant joins so audio subscription is set up in time.
    LOGGER.info(f"[{call_id}] Starting session")
    session_task = asyncio.create_task(
        session.start(
            agent=RealEstateAgent(),
            room=ctx.room,
            room_input_options=RoomInputOptions(
                audio_enabled=True,
                # Pin the input to the SIP customer leg so the agent always reads
                # the right participant's audio (no ambiguity / wrong-track bugs).
                participant_identity=SIP_PARTICIPANT_IDENTITY,
                # Telephony has no browser client to send a pre-connect audio
                # buffer; leaving this on makes RoomIO wait pointlessly. Off = audio
                # from the live SIP track flows immediately.
                pre_connect_audio=False,
                # 8 kHz G.711 narrowband — BVC/noise-cancellation can drop it.
                noise_cancellation=None,
                # A hangup / SIP disconnect closes the session → drives call_ended.
                close_on_disconnect=True,
            ),
        )
    )

    # ── Place outbound SIP call ────────────────────────────────────────────────
    LOGGER.info(f"[{call_id}] Placing SIP call to {phone}")
    try:
        await ctx.api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=ctx.room.name,
                sip_trunk_id=SETTINGS.SIP_OUTBOUND_TRUNK_ID,
                sip_call_to=phone,
                participant_identity=SIP_PARTICIPANT_IDENTITY,
                participant_name="Customer",
                wait_until_answered=True,
            )
        )
        LOGGER.info(f"[{call_id}] Customer answered")
        call_state["answered"] = True
        call_state["status"] = "completed"
        # Tell the frontend the call is live → flips the badge to "● Live".
        CONNECTION_MANAGER.broadcast_from_thread(call_id, {
            "type":    "call_connected",
            "call_id": call_id,
        })
    except Exception as e:
        LOGGER.error(f"[{call_id}] SIP call failed: {e}")
        call_state["status"] = "failed"
        session_task.cancel()
        return

    await session_task

    # ── Opening greeting (persona-driven, not hardcoded) ───────────────────────
    LOGGER.info(f"[{call_id}] Triggering greeting")
    greeting_handle = session.generate_reply(
        instructions=(
            "The call just connected. Greet the customer warmly as Arjun from HomePro Realty. "
            "Be natural and conversational — no scripts, no bullet points."
        )
    )

    # ── Silence fallback — starts AFTER greeting finishes, not when call connects
    # Counting from call connect left only ~5s after a ~7s greeting. Now the user
    # gets a full 18s to respond once they've finished hearing the greeting.
    def _on_greeting_done(_) -> None:
        LOGGER.info(f"[{call_id}] Greeting done — starting 18s silence watch")

        async def _silence_fallback() -> None:
            await asyncio.sleep(18)
            if not any(t.get("role") == "user" for t in transcript):
                LOGGER.warning(f"[{call_id}] No user speech 18s after greeting — nudging")
                session.generate_reply(
                    instructions="Gently ask if the customer can hear you. One sentence only."
                )

        asyncio.create_task(_silence_fallback())

    greeting_handle.add_done_callback(_on_greeting_done)


def create_agent_server() -> AgentServer:
    server = AgentServer(
        ws_url=SETTINGS.LIVEKIT_URL,
        api_key=SETTINGS.LIVEKIT_API_KEY,
        api_secret=SETTINGS.LIVEKIT_API_SECRET,
        job_executor_type=JobExecutorType.THREAD,
        num_idle_processes=0,
    )

    @server.rtc_session(agent_name=AGENT_NAME)
    async def _entrypoint(ctx: JobContext) -> None:
        await entrypoint(ctx)

    return server


if __name__ == "__main__":
    from livekit.agents import cli, WorkerOptions

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            ws_url=SETTINGS.LIVEKIT_URL,
            api_key=SETTINGS.LIVEKIT_API_KEY,
            api_secret=SETTINGS.LIVEKIT_API_SECRET,
            agent_name=AGENT_NAME,
        )
    )
