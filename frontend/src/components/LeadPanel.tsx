"use client";

import { LeadData } from "@/types";

interface Props {
  lead: Partial<LeadData>;
  isHot: boolean;
}

const INTEREST_BADGE: Record<string, string> = {
  cold: "bg-blue-100 text-blue-700",
  warm: "bg-yellow-100 text-yellow-700",
  hot: "bg-red-100 text-red-700",
};

export default function LeadPanel({ lead, isHot }: Props) {
  const fields: { label: string; value: string | undefined }[] = [
    { label: "Name", value: lead.name },
    { label: "Location", value: lead.location },
    {
      label: "Budget",
      value:
        lead.budget_min || lead.budget_max
          ? [
              lead.budget_min ? `₹${lead.budget_min}L` : null,
              lead.budget_max ? `₹${lead.budget_max}L` : null,
            ]
              .filter(Boolean)
              .join(" – ")
          : undefined,
    },
    { label: "BHK", value: lead.bhk ? `${lead.bhk} BHK` : undefined },
    { label: "Type", value: lead.property_type },
    {
      label: "Timeline",
      value:
        lead.ready_to_move === true
          ? "Ready to Move"
          : lead.ready_to_move === false
          ? "Under Construction"
          : undefined,
    },
    { label: "Purpose", value: lead.purpose?.replace("_", " ") },
  ];

  const filled = fields.filter((f) => f.value).length;

  return (
    <div className="bg-white rounded-2xl shadow-lg p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-bold text-gray-700">🎯 Lead Details</h2>
        {isHot && (
          <span className="text-xs font-semibold bg-red-500 text-white px-2 py-0.5 rounded-full animate-pulse">
            🔥 HOT LEAD
          </span>
        )}
      </div>

      <div className="space-y-2">
        {fields.map(({ label, value }) => (
          <div key={label} className="flex items-center justify-between text-sm">
            <span className="text-gray-400 text-xs">{label}</span>
            {value ? (
              <span className="font-medium text-gray-800 text-xs">{value}</span>
            ) : (
              <span className="text-gray-200 text-xs">—</span>
            )}
          </div>
        ))}
      </div>

      {lead.interest_level && (
        <div className="mt-4 flex items-center gap-2">
          <span className="text-xs text-gray-400">Interest</span>
          <span
            className={`text-xs font-semibold px-2 py-0.5 rounded-full capitalize ${
              INTEREST_BADGE[lead.interest_level] || "bg-gray-100 text-gray-500"
            }`}
          >
            {lead.interest_level}
          </span>
        </div>
      )}

      <div className="mt-4 h-1 bg-gray-100 rounded-full">
        <div
          className="h-1 bg-blue-500 rounded-full transition-all duration-500"
          style={{ width: `${Math.round((filled / fields.length) * 100)}%` }}
        />
      </div>
      <div className="text-xs text-gray-400 mt-1">{filled}/{fields.length} fields captured</div>
    </div>
  );
}
