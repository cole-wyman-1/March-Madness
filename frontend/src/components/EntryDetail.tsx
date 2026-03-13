"use client";

import { useEffect, useState } from "react";
import type { EntryDetail as EntryDetailType, BracketPick } from "@/lib/types";
import { getEntryDetail } from "@/lib/api";

const ROUND_NAMES: Record<number, string> = {
  1: "Round of 64",
  2: "Round of 32",
  3: "Sweet 16",
  4: "Elite 8",
  5: "Final Four",
  6: "Championship",
};

const ROUND_POINTS: Record<number, number> = {
  1: 10,
  2: 20,
  3: 40,
  4: 80,
  5: 160,
  6: 320,
};

interface EntryDetailProps {
  entryId: string;
  onClose: () => void;
}

export default function EntryDetail({ entryId, onClose }: EntryDetailProps) {
  const [detail, setDetail] = useState<EntryDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getEntryDetail(entryId)
      .then((d) => {
        setDetail(d);
        setLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to load entry");
        setLoading(false);
      });
  }, [entryId]);

  if (loading) {
    return (
      <div className="bg-gray-900/50 rounded-xl border border-gray-800 p-6">
        <div className="text-gray-500">Loading bracket...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-gray-900/50 rounded-xl border border-gray-800 p-6">
        <div className="flex items-center justify-between">
          <span className="text-sm text-red-400">{error}</span>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-200 text-sm px-3 py-1 rounded border border-gray-700 hover:border-gray-500 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    );
  }

  if (!detail) return null;

  const picksByRound: Record<number, BracketPick[]> = {};
  for (const pick of detail.picks) {
    if (!picksByRound[pick.round]) picksByRound[pick.round] = [];
    picksByRound[pick.round].push(pick);
  }

  return (
    <div className="bg-gray-900/50 rounded-xl border border-gray-800 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold">{detail.entry_name}</h3>
          <p className="text-xs text-gray-500">
            by {detail.owner_name} &middot; Score: {detail.current_score}
          </p>
        </div>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-gray-200 text-sm px-3 py-1 rounded border border-gray-700 hover:border-gray-500 transition-colors"
        >
          Close
        </button>
      </div>

      <div className="p-4 space-y-4">
        {[1, 2, 3, 4, 5, 6].map((round) => {
          const picks = picksByRound[round] || [];
          if (picks.length === 0) return null;

          const correct = picks.filter((p) => p.is_correct === true).length;
          const decided = picks.filter((p) => p.is_correct !== null).length;
          const pts = ROUND_POINTS[round];

          return (
            <div key={round}>
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-sm font-medium text-gray-300">
                  {ROUND_NAMES[round]}
                  <span className="text-gray-500 ml-2 font-normal">
                    {pts} pts each
                  </span>
                </h4>
                {decided > 0 && (
                  <span className="text-xs text-gray-500">
                    {correct}/{decided} correct &middot;{" "}
                    {correct * pts} pts
                  </span>
                )}
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
                {picks.map((pick) => (
                  <PickChip key={pick.game_id} pick={pick} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PickChip({ pick }: { pick: BracketPick }) {
  let bg = "bg-gray-800 border-gray-700"; // undecided
  let icon = "";

  if (pick.is_correct === true) {
    bg = "bg-emerald-900/40 border-emerald-700/50";
    icon = "✓";
  } else if (pick.is_correct === false) {
    bg = "bg-red-900/30 border-red-800/50";
    icon = "✗";
  }

  return (
    <div
      className={`${bg} border rounded px-2.5 py-1.5 text-xs flex items-center justify-between`}
    >
      <span className="truncate">{pick.team_name}</span>
      {icon && (
        <span
          className={
            pick.is_correct
              ? "text-emerald-400 ml-1.5 flex-shrink-0"
              : "text-red-400 ml-1.5 flex-shrink-0"
          }
        >
          {icon}
        </span>
      )}
    </div>
  );
}
