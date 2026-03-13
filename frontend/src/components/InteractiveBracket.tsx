"use client";

import { useCallback } from "react";
import type {
  ProjectionResult,
  ProjectionsResponse,
} from "@/lib/types";

/**
 * Interactive tournament bracket with dual sliders and team dropdowns.
 *
 * - Confirmed matchups (R64, or later rounds where both teams are known):
 *   Show dual opposing sliders — each team has its own slider that mirrors the other.
 * - Unconfirmed matchups (later rounds, participants TBD):
 *   Show a dropdown of all eligible teams sorted by win probability.
 *
 * Layout:
 *   Left:   East (top) + West (bottom), left→right
 *   Right:  South (top) + Midwest (bottom), right→left
 *   Center: Final Four + Championship
 */

const REGIONS = [
  { name: "East", index: 0, r64Base: 1, r32Base: 33, s16Base: 49, e8: 57 },
  { name: "West", index: 1, r64Base: 9, r32Base: 37, s16Base: 51, e8: 58 },
  { name: "South", index: 2, r64Base: 17, r32Base: 41, s16Base: 53, e8: 59 },
  {
    name: "Midwest",
    index: 3,
    r64Base: 25,
    r32Base: 45,
    s16Base: 55,
    e8: 60,
  },
];

interface InteractiveBracketProps {
  projections: ProjectionsResponse;
  overrides: Map<number, number>;
  locks: Map<number, string>;
  onOverride: (gameId: number, probAWins: number) => void;
  onLock: (gameId: number, team: string) => void;
  onRun: () => void;
  onReset: () => void;
  isSimulating: boolean;
  hasChanges: boolean;
}

export default function InteractiveBracket({
  projections,
  overrides,
  locks,
  onOverride,
  onLock,
  onRun,
  onReset,
  isSimulating,
  hasChanges,
}: InteractiveBracketProps) {
  const projMap = new Map<number, ProjectionResult>();
  for (const p of projections.projections) {
    projMap.set(p.game_id, p);
  }

  return (
    <div className="bg-gray-900/50 rounded-xl border border-gray-800 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Interactive Bracket</h2>
          <p className="text-xs text-gray-500">
            Adjust sliders or select winners, then press Run to simulate
          </p>
        </div>
        <div className="flex items-center gap-2">
          {hasChanges && (
            <button
              onClick={onReset}
              className="text-gray-400 hover:text-gray-200 text-sm px-3 py-1.5 rounded border border-gray-700 hover:border-gray-500 transition-colors"
            >
              Reset
            </button>
          )}
          <button
            onClick={onRun}
            disabled={isSimulating || !hasChanges}
            className={`text-sm px-4 py-1.5 rounded font-medium transition-colors ${
              isSimulating || !hasChanges
                ? "bg-gray-700 text-gray-500 cursor-not-allowed"
                : "bg-blue-600 hover:bg-blue-500 text-white"
            }`}
          >
            {isSimulating ? "Running..." : "Run Simulation"}
          </button>
        </div>
      </div>

      <div className="p-4 overflow-x-auto">
        <div className="flex items-stretch gap-0 min-w-[1100px]">
          {/* Left side: East (top) + West (bottom) */}
          <div className="flex flex-col gap-4 flex-1">
            <RegionBracket
              region={REGIONS[0]}
              projMap={projMap}
              overrides={overrides}
              locks={locks}
              onOverride={onOverride}
              onLock={onLock}
              direction="ltr"
            />
            <RegionBracket
              region={REGIONS[1]}
              projMap={projMap}
              overrides={overrides}
              locks={locks}
              onOverride={onOverride}
              onLock={onLock}
              direction="ltr"
            />
          </div>

          {/* Center: Final Four + Championship */}
          <FinalRounds
            projMap={projMap}
            overrides={overrides}
            locks={locks}
            onOverride={onOverride}
            onLock={onLock}
          />

          {/* Right side: South (top) + Midwest (bottom) */}
          <div className="flex flex-col gap-4 flex-1">
            <RegionBracket
              region={REGIONS[2]}
              projMap={projMap}
              overrides={overrides}
              locks={locks}
              onOverride={onOverride}
              onLock={onLock}
              direction="rtl"
            />
            <RegionBracket
              region={REGIONS[3]}
              projMap={projMap}
              overrides={overrides}
              locks={locks}
              onOverride={onOverride}
              onLock={onLock}
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
  projMap,
  overrides,
  locks,
  onOverride,
  onLock,
  direction,
}: {
  region: RegionDef;
  projMap: Map<number, ProjectionResult>;
  overrides: Map<number, number>;
  locks: Map<number, string>;
  onOverride: (gameId: number, prob: number) => void;
  onLock: (gameId: number, team: string) => void;
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
            projMap={projMap}
            overrides={overrides}
            locks={locks}
            onOverride={onOverride}
            onLock={onLock}
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
  projMap,
  overrides,
  locks,
  onOverride,
  onLock,
  isFirst,
}: {
  gameIds: number[];
  projMap: Map<number, ProjectionResult>;
  overrides: Map<number, number>;
  locks: Map<number, string>;
  onOverride: (gameId: number, prob: number) => void;
  onLock: (gameId: number, team: string) => void;
  isFirst: boolean;
}) {
  return (
    <div
      className={`flex flex-col justify-around flex-1 ${isFirst ? "" : "pl-0.5"}`}
      style={{ minWidth: 0 }}
    >
      {gameIds.map((gid) => {
        const proj = projMap.get(gid);
        return (
          <GameSlotCard
            key={gid}
            gameId={gid}
            projection={proj}
            override={overrides.get(gid)}
            lock={locks.get(gid)}
            onOverride={onOverride}
            onLock={onLock}
          />
        );
      })}
    </div>
  );
}

/* ---------- Game Slot Card ---------- */

function GameSlotCard({
  gameId,
  projection,
  override,
  lock,
  onOverride,
  onLock,
}: {
  gameId: number;
  projection: ProjectionResult | undefined;
  override: number | undefined;
  lock: string | undefined;
  onOverride: (gameId: number, prob: number) => void;
  onLock: (gameId: number, team: string) => void;
}) {
  if (!projection) {
    return (
      <div className="mx-0.5 my-[2px]">
        <div className="h-12 bg-gray-800/50 rounded-sm border border-gray-800" />
      </div>
    );
  }

  const { is_completed, eligible_teams } = projection;

  if (is_completed) {
    return <CompletedSlot projection={projection} />;
  }

  // Unconfirmed: eligible_teams populated with >2 possible teams
  const isUnconfirmed = eligible_teams !== null && eligible_teams.length > 2;

  if (isUnconfirmed) {
    return (
      <UnconfirmedSlot
        gameId={gameId}
        projection={projection}
        lock={lock}
        onLock={onLock}
      />
    );
  }

  return (
    <ConfirmedSlot
      gameId={gameId}
      projection={projection}
      override={override}
      lock={lock}
      onOverride={onOverride}
      onLock={onLock}
    />
  );
}

/* ---------- Completed Game ---------- */

function CompletedSlot({ projection }: { projection: ProjectionResult }) {
  const { team_a, team_b, prob_a_wins } = projection;
  const winnerIsA = prob_a_wins === 1.0;

  return (
    <div className="mx-0.5 my-[2px]">
      <div className="bg-gray-800/40 border border-gray-700/40 rounded-sm px-1.5 py-0.5">
        <div className="flex items-center justify-between">
          <span
            className={`text-[10px] truncate ${winnerIsA ? "text-emerald-300 font-medium" : "text-gray-500 line-through"}`}
          >
            {team_a}
          </span>
          <span className="text-[9px] text-gray-600 ml-1">
            {winnerIsA ? "W" : "L"}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span
            className={`text-[10px] truncate ${!winnerIsA ? "text-emerald-300 font-medium" : "text-gray-500 line-through"}`}
          >
            {team_b}
          </span>
          <span className="text-[9px] text-gray-600 ml-1">
            {!winnerIsA ? "W" : "L"}
          </span>
        </div>
      </div>
    </div>
  );
}

/* ---------- Confirmed Matchup: Dual Opposing Sliders ---------- */

function ConfirmedSlot({
  gameId,
  projection,
  override,
  lock,
  onOverride,
  onLock,
}: {
  gameId: number;
  projection: ProjectionResult;
  override: number | undefined;
  lock: string | undefined;
  onOverride: (gameId: number, prob: number) => void;
  onLock: (gameId: number, team: string) => void;
}) {
  const { team_a, team_b, prob_a_wins } = projection;
  const displayProb = override !== undefined ? override : prob_a_wins;
  const probA = Math.round(displayProb * 100);
  const probB = 100 - probA;
  const isLocked = lock !== undefined;
  const lockIsA = lock === team_a;
  const lockIsB = lock === team_b;
  const isModified = override !== undefined;

  const handleSliderA = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onOverride(gameId, parseInt(e.target.value) / 100);
    },
    [gameId, onOverride]
  );

  const handleSliderB = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onOverride(gameId, 1 - parseInt(e.target.value) / 100);
    },
    [gameId, onOverride]
  );

  const handleLockA = useCallback(() => {
    onLock(gameId, lock === team_a ? "" : team_a);
  }, [gameId, team_a, lock, onLock]);

  const handleLockB = useCallback(() => {
    onLock(gameId, lock === team_b ? "" : team_b);
  }, [gameId, team_b, lock, onLock]);

  const borderClass = isModified
    ? "border-blue-700/60 bg-blue-900/20"
    : isLocked
      ? "border-yellow-700/60 bg-yellow-900/15"
      : "border-gray-700/60 bg-gray-800/80";

  const sliderColorA = isModified ? "#3b82f6" : lockIsA ? "#eab308" : "#10b981";
  const sliderColorB = isModified ? "#3b82f6" : lockIsB ? "#eab308" : "#10b981";

  return (
    <div className="mx-0.5 my-[2px]">
      <div className={`border rounded-sm px-1.5 py-0.5 ${borderClass}`}>
        {/* Team A */}
        <div>
          <div className="flex items-center justify-between">
            <button
              onClick={handleLockA}
              className={`text-[10px] truncate text-left transition-colors ${
                lockIsA
                  ? "text-yellow-200 font-semibold"
                  : "text-gray-300 hover:text-white"
              }`}
              title={`${lockIsA ? "Unlock" : "Lock"} ${team_a}`}
            >
              {lockIsA && "🔒"}{team_a}
            </button>
            <span
              className={`text-[9px] tabular-nums font-medium ml-1 ${
                probA >= 50 ? "text-emerald-400" : "text-gray-500"
              }`}
            >
              {probA}%
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            value={probA}
            onChange={handleSliderA}
            disabled={isLocked}
            className={`w-full h-1.5 appearance-none rounded-full cursor-pointer
              ${isLocked ? "opacity-30 cursor-not-allowed" : ""}
              [&::-webkit-slider-thumb]:appearance-none
              [&::-webkit-slider-thumb]:w-2.5
              [&::-webkit-slider-thumb]:h-2.5
              [&::-webkit-slider-thumb]:rounded-full
              [&::-webkit-slider-thumb]:bg-white
              [&::-webkit-slider-thumb]:shadow-sm
            `}
            style={{
              background: `linear-gradient(to right, ${sliderColorA} ${probA}%, #374151 ${probA}%)`,
            }}
          />
        </div>

        {/* Team B */}
        <div className="mt-0.5">
          <div className="flex items-center justify-between">
            <button
              onClick={handleLockB}
              className={`text-[10px] truncate text-left transition-colors ${
                lockIsB
                  ? "text-yellow-200 font-semibold"
                  : "text-gray-300 hover:text-white"
              }`}
              title={`${lockIsB ? "Unlock" : "Lock"} ${team_b}`}
            >
              {lockIsB && "🔒"}{team_b}
            </button>
            <span
              className={`text-[9px] tabular-nums font-medium ml-1 ${
                probB >= 50 ? "text-emerald-400" : "text-gray-500"
              }`}
            >
              {probB}%
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            value={probB}
            onChange={handleSliderB}
            disabled={isLocked}
            className={`w-full h-1.5 appearance-none rounded-full cursor-pointer
              ${isLocked ? "opacity-30 cursor-not-allowed" : ""}
              [&::-webkit-slider-thumb]:appearance-none
              [&::-webkit-slider-thumb]:w-2.5
              [&::-webkit-slider-thumb]:h-2.5
              [&::-webkit-slider-thumb]:rounded-full
              [&::-webkit-slider-thumb]:bg-white
              [&::-webkit-slider-thumb]:shadow-sm
            `}
            style={{
              background: `linear-gradient(to right, ${sliderColorB} ${probB}%, #374151 ${probB}%)`,
            }}
          />
        </div>
      </div>
    </div>
  );
}

/* ---------- Unconfirmed Matchup: Team Dropdown ---------- */

function UnconfirmedSlot({
  gameId,
  projection,
  lock,
  onLock,
}: {
  gameId: number;
  projection: ProjectionResult;
  lock: string | undefined;
  onLock: (gameId: number, team: string) => void;
}) {
  const { eligible_teams } = projection;
  const teams = eligible_teams || [];

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      onLock(gameId, e.target.value);
    },
    [gameId, onLock]
  );

  const handleUnlock = useCallback(() => {
    onLock(gameId, "");
  }, [gameId, onLock]);

  if (lock) {
    const lockedTeam = teams.find((t) => t.team === lock);
    const prob = lockedTeam ? Math.round(lockedTeam.prob * 100) : 0;

    return (
      <div className="mx-0.5 my-[2px]">
        <div className="border border-yellow-700/60 bg-yellow-900/15 rounded-sm px-1.5 py-1">
          <div className="flex items-center justify-between gap-1">
            <span className="text-[10px] text-yellow-200 font-semibold truncate">
              🔒 {lock}
            </span>
            <span className="text-[9px] text-yellow-400/70 tabular-nums">
              {prob}%
            </span>
            <button
              onClick={handleUnlock}
              className="text-[9px] text-gray-500 hover:text-gray-300 ml-1"
              title="Unlock"
            >
              ✕
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-0.5 my-[2px]">
      <div className="border border-gray-700/60 bg-gray-800/80 rounded-sm px-1 py-0.5">
        <select
          value=""
          onChange={handleChange}
          className="w-full bg-transparent text-[10px] text-gray-400 cursor-pointer
            focus:outline-none focus:text-gray-200
            [&>option]:bg-gray-800 [&>option]:text-gray-200"
        >
          <option value="" disabled>
            Select winner...
          </option>
          {teams.map((t) => (
            <option key={t.team} value={t.team}>
              {t.team} ({Math.round(t.prob * 100)}%)
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

/* ---------- Final Rounds (F4 + NCG) ---------- */

function FinalRounds({
  projMap,
  overrides,
  locks,
  onOverride,
  onLock,
}: {
  projMap: Map<number, ProjectionResult>;
  overrides: Map<number, number>;
  locks: Map<number, string>;
  onOverride: (gameId: number, prob: number) => void;
  onLock: (gameId: number, team: string) => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-3 gap-1 min-w-[160px]">
      <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">
        Final Four
      </div>
      <GameSlotCard
        gameId={61}
        projection={projMap.get(61)}
        override={overrides.get(61)}
        lock={locks.get(61)}
        onOverride={onOverride}
        onLock={onLock}
      />
      <div className="my-1 w-full">
        <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider text-center">
          Champion
        </div>
        <div className="mt-0.5">
          <GameSlotCard
            gameId={63}
            projection={projMap.get(63)}
            override={overrides.get(63)}
            lock={locks.get(63)}
            onOverride={onOverride}
            onLock={onLock}
          />
        </div>
      </div>
      <GameSlotCard
        gameId={62}
        projection={projMap.get(62)}
        override={overrides.get(62)}
        lock={locks.get(62)}
        onOverride={onOverride}
        onLock={onLock}
      />
    </div>
  );
}
