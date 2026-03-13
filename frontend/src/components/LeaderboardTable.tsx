"use client";

import { useState } from "react";
import type { StandingsResult } from "@/lib/types";
import ProbabilityBar from "./ProbabilityBar";

interface LeaderboardTableProps {
  standings: StandingsResult[];
  gamesRemaining: number;
  onSelectEntry?: (entryId: string) => void;
}

type SortKey = "rank" | "win" | "top3" | "score" | "expected";

export default function LeaderboardTable({
  standings,
  gamesRemaining,
  onSelectEntry,
}: LeaderboardTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("win");
  const [sortAsc, setSortAsc] = useState(false);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(false);
    }
  };

  const sorted = [...standings].sort((a, b) => {
    let diff = 0;
    switch (sortKey) {
      case "rank":
        diff = a.current_score - b.current_score;
        break;
      case "win":
        diff = (a.rank_probabilities[1] ?? 0) - (b.rank_probabilities[1] ?? 0);
        break;
      case "top3":
        diff = a.top_3_prob - b.top_3_prob;
        break;
      case "score":
        diff = a.current_score - b.current_score;
        break;
      case "expected":
        diff = a.expected_final_score - b.expected_final_score;
        break;
    }
    return sortAsc ? diff : -diff;
  });

  const SortHeader = ({
    label,
    sortKeyVal,
    className,
  }: {
    label: string;
    sortKeyVal: SortKey;
    className?: string;
  }) => (
    <th
      className={`px-3 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider cursor-pointer hover:text-gray-200 select-none ${className ?? ""}`}
      onClick={() => handleSort(sortKeyVal)}
    >
      {label}
      {sortKey === sortKeyVal && (
        <span className="ml-1">{sortAsc ? "▲" : "▼"}</span>
      )}
    </th>
  );

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-gray-800">
            <th className="px-3 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider w-10">
              #
            </th>
            <th className="px-3 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
              Entry
            </th>
            <SortHeader label="Score" sortKeyVal="score" className="w-20" />
            <SortHeader label="Proj" sortKeyVal="expected" className="w-20" />
            <SortHeader label="Win%" sortKeyVal="win" className="w-44" />
            <SortHeader label="Top 3" sortKeyVal="top3" className="w-44" />
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800/50">
          {sorted.map((entry, i) => {
            const winPct = entry.rank_probabilities[1] ?? 0;
            return (
              <tr
                key={entry.entry_id}
                className="hover:bg-gray-900/50 cursor-pointer transition-colors"
                onClick={() => onSelectEntry?.(entry.entry_id)}
              >
                <td className="px-3 py-3 text-sm text-gray-500 font-mono">
                  {i + 1}
                </td>
                <td className="px-3 py-3">
                  <div className="text-sm font-medium">{entry.entry_name}</div>
                </td>
                <td className="px-3 py-3 text-sm font-mono">
                  {entry.current_score}
                </td>
                <td className="px-3 py-3 text-sm font-mono text-gray-400">
                  {entry.expected_final_score.toFixed(0)}
                </td>
                <td className="px-3 py-3">
                  <ProbabilityBar
                    value={winPct}
                    color={
                      winPct > 0.3
                        ? "bg-emerald-500"
                        : winPct > 0.1
                          ? "bg-yellow-500"
                          : "bg-gray-600"
                    }
                  />
                </td>
                <td className="px-3 py-3">
                  <ProbabilityBar
                    value={entry.top_3_prob}
                    color="bg-blue-500"
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {gamesRemaining > 0 && (
        <div className="text-xs text-gray-500 mt-3 px-3">
          {gamesRemaining} games remaining
        </div>
      )}
    </div>
  );
}
