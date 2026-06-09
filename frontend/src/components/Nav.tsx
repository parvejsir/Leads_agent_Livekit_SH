"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export default function Nav({ children }: { children?: React.ReactNode }) {
  const pathname = usePathname();
  const links = [
    { href: "/", label: "Dashboard" },
    { href: "/history", label: "Call History" },
  ];

  return (
    <header className="bg-white shadow-sm border-b border-gray-200">
      <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center text-white font-bold text-sm">
              H
            </div>
            <div>
              <h1 className="text-base font-bold text-gray-800">HomePro Realty</h1>
              <p className="text-xs text-gray-400">AI Voice Lead Generation</p>
            </div>
          </div>

          <nav className="flex items-center gap-1">
            {links.map((l) => {
              const active = pathname === l.href;
              return (
                <Link
                  key={l.href}
                  href={l.href}
                  className={`text-sm px-3 py-1.5 rounded-lg font-medium transition-colors ${
                    active
                      ? "bg-blue-50 text-blue-700"
                      : "text-gray-500 hover:bg-gray-100 hover:text-gray-800"
                  }`}
                >
                  {l.label}
                </Link>
              );
            })}
          </nav>
        </div>

        <div className="flex items-center gap-2">{children}</div>
      </div>
    </header>
  );
}
