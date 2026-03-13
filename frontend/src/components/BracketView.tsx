"use client";

import { useEffect, useState } from "react";
import type { EntryDetail as EntryDetailType, BracketPick } from "@/lib/types";
import { getEntryDetail } from "@/lib/api";

/**
 * Bracket visualization — renders picks in the classic tournament bracket shape.
 *
 * Layout:
 *   Left side:  Region 1 (top) + Region 2 (bottom) flowing left→right
 *   Right side: Region 3 (top) + Region 4 (bottom) flowing right→left
 *   Center:     Final Four + Championship
 *
 * Game ID mapping (canonical):
 *   Region 0 (East):    R64=1-8,   R32=33-36, S16=49-50, E8=57
 *   Region 1 (West):    R64=9-16,  R32=37-40, S16=51-52, E8=58
 *   Region 2 (South):   R64=17-24, R32=41-44, S16=53-54, E8=59
 *   Region 3 (Midwest): R64=25-32, R32=45-48, S16=55-56, E8=60
 *   F4: 61 (R0 vs R1), 62 (R2 vs R3)
 *   NCG: 63
 */

const REGIONS = [
  { name: "East", index: 0, r64Base: 1, r32Base: 33, s16Base: 49, e8: 57 },
  { name: "West", index: 1, r64Base: 9, r32Base: 37, s16Base: 51, e8: 58 },
  { name: "South", index: 2, r64Base: 17, r32Base: 41, s16Base: 53, e8: 59 },
  { name: "Midwest", index: 3, r64Base: 25, r32Base: 45, s16Base: 55, e8: 60 },
];

interface BracketViewProps {
  entryId: string;
  onClose: () => void;
}

export default function BracketView({ entryId, onClose }: BracketViewProps) {
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
        setError(err instanceof Error ? err.message : "Failed to load bracket");
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

  const pickMap = new Map<number, BracketPick>();
  for (const p of detail.picks) {
    pickMap.set(p.game_id, p);
  }

  return (
    <div className="bg-gray-900/50 rounded-xl border border-gray-800 overflow-hidden">
      {/* Header */}
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

      {/* Bracket */}
      <div className="p-4 overflow-x-auto">
        <div className="flex items-stretch gap-0 min-w-[900px]">
          {/* Left side: East (top) + West (bottom) */}
          <div className="flex flex-col gap-2 flex-1">
            <RegionBracket
              region={REGIONS[0]}
              pickMap={pickMap}
              direction="ltr"
            />
            <RegionBracket
              region={REGIONS[1]}
              pickMap={pickMap}
              direction="ltr"
            />
          </div>

          {/* Center: Final Four + Championship */}
          <FinalRounds pickMap={pickMap} />

          {/* Right side: South (top) + Midwest (bottom) */}
          <div className="flex flex-col gap-2 flex-1">
            <RegionBracket
              region={REGIONS[2]}
              pickMap={pickMap}
              direction="rtl"
            />
            <RegionBracket
              region={REGIONS[3]}
              pickMap={pickMap}
              direction="rtl"
            />
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------- Region Bracket ---------- */

interface RegionDef {
  name: string;
  index: number;
  r64Base: number;
  r32Base: number;
  s16Base: number;
  e8: number;
}

function RegionBracket({
  region,
  pickMap,
  direction,
}: {
  region: RegionDef;
  pickMap: Map<number, BracketPick>;
  direction: "ltr" | "rtl";
}) {
  const r64 = Array.from({ length: 8 }, (_, i) => region.r64Base + i);
  const r32 = Array.from({ length: 4 }, (_, i) => region.r32Base + i);
  const s16 = Array.from({ length: 2 }, (_, i) => region.s16Base + i);
  const e8 = [region.e8];

  const rounds = [r64, r32, s16, e8];
  const orderedRounds = direction === "rtl" ? [...rounds].reverse() : rounds;

  return (
    <div>
      <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1 px-1">
        {region.name}
      </div>
      <div className="flex items-stretch">
        {orderedRounds.map((gameIds, colIdx) => (
          <RoundColumn
            key={colIdx}
            gameIds={gameIds}
            pickMap={pickMap}
            isFirst={colIdx === 0}
          />
        ))}
      </div>
    </div>
  );
}

/* ---------- Round Column ---------- */

function RoundColumn({
  gameIds,
  pickMap,
  isFirst,
}: {
  gameIds: number[];
  pickMap: Map<number, BracketPick>;
  isFirst: boolean;
}) {
  return (
    <div
      className={`flex flex-col justify-around flex-1 ${isFirst ? "" : "pl-0.5"}`}
      style={{ minWidth: 0 }}
    >
      {gameIds.map((gid) => {
        const pick = pickMap.get(gid);
        return <PickSlot key={gid} pick={pick} />;
      })}
    </div>
  );
}

/* ---------- Pick Slot ---------- */

function PickSlot({ pick }: { pick: BracketPick | undefined }) {
  if (!pick) {
    return (
      <div className="mx-0.5 my-[1px]">
        <div className="h-5 bg-gray-800/50 rounded-sm border border-gray-800" />
      </div>
    );
  }

  let bg: string;
  let textColor: string;
  let borderColor: string;

  if (pick.is_correct === true) {
    bg = "bg-emerald-900/50";
    textColor = "text-emerald-200";
    borderColor = "border-emerald-700/60";
  } else if (pick.is_correct === false) {
    bg = "bg-red-900/40";
    textColor = "text-red-300/80 line-through";
    borderColor = "border-red-800/50";
  } else {
    bg = "bg-gray-800/80";
    textColor = "text-gray-300";
    borderColor = "border-gray-700/60";
  }

  return (
    <div className="mx-0.5 my-[1px]">
      <div
        className={`${bg} ${borderColor} border rounded-sm px-1.5 py-0.5 truncate`}
        title={pick.team_name}
      >
        <span className={`text-[10px] leading-tight ${textColor}`}>
          {pick.team_name}
        </span>
      </div>
    </div>
  );
}

/* ---------- Final Rounds (F4 + NCG) ---------- */

function FinalRounds({
  pickMap,
}: {
  pickMap: Map<number, BracketPick>;
}) {
  const f4a = pickMap.get(61); // East vs West winner
  const f4b = pickMap.get(62); // South vs Midwest winner
  const ncg = pickMap.get(63); // Champion

  return (
    <div className="flex flex-col items-center justify-center px-3 gap-1 min-w-[90px]">
      <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">
        Final Four
      </div>
      <PickSlot pick={f4a} />
      <div className="my-1">
        <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">
          Champion
        </div>
        <div className="mt-0.5">
          <ChampionSlot pick={ncg} />
        </div>
      </div>
      <PickSlot pick={f4b} />
    </div>
  );
}

function ChampionSlot({ pick }: { pick: BracketPick | undefined }) {
  if (!pick) {
    return (
      <div className="h-7 w-full bg-gray-800/50 rounded border border-gray-700 border-dashed" />
    );
  }

  let bg: string;
  let textColor: string;
  let borderColor: string;

  if (pick.is_correct === true) {
    bg = "bg-emerald-900/60";
    textColor = "text-emerald-100 font-semibold";
    borderColor = "border-emerald-600";
  } else if (pick.is_correct === false) {
    bg = "bg-red-900/50";
    textColor = "text-red-300 line-through";
    borderColor = "border-red-700";
  } else {
    bg = "bg-yellow-900/30";
    textColor = "text-yellow-200 font-semibold";
    borderColor = "border-yellow-700/60";
  }

  return (
    <div
      className={`${bg} ${borderColor} border rounded px-2 py-1 text-center`}
      title={pick.team_name}
    >
      <span className={`text-xs ${textColor}`}>{pick.team_name}</span>
    </div>
  );
}
