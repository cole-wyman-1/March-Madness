"use client";

import type { GroupInfo } from "@/lib/types";

interface GroupSelectorProps {
  groups: GroupInfo[];
  selectedId: string | null;
  onSelect: (groupId: string) => void;
}

export default function GroupSelector({
  groups,
  selectedId,
  onSelect,
}: GroupSelectorProps) {
  if (groups.length === 0) {
    return (
      <div className="text-gray-500 text-sm">No groups loaded yet.</div>
    );
  }

  return (
    <div className="flex items-center gap-3">
      <label className="text-sm text-gray-400">Group:</label>
      <select
        value={selectedId ?? ""}
        onChange={(e) => onSelect(e.target.value)}
        className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
      >
        {groups.map((g) => (
          <option key={g.group_id} value={g.group_id}>
            {g.group_name} ({g.entry_count} entries)
          </option>
        ))}
      </select>
    </div>
  );
}
