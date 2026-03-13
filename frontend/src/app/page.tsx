"use client";

import { useCallback, useEffect, useState } from "react";
import type {
  GroupInfo,
  GroupStandings,
  ProjectionsResponse,
  StandingsResult,
} from "@/lib/types";
import {
  getGroups,
  getStandings,
  getProjections,
  simulate,
  addGroup,
  refreshGroup,
  deleteGroup,
} from "@/lib/api";
import GroupSelector from "@/components/GroupSelector";
import LeaderboardTable from "@/components/LeaderboardTable";
import BracketView from "@/components/BracketView";
import InteractiveBracket from "@/components/InteractiveBracket";

export default function Home() {
  const [groups, setGroups] = useState<GroupInfo[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);
  const [standings, setStandings] = useState<GroupStandings | null>(null);
  const [selectedEntryId, setSelectedEntryId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Add group form state
  const [showAddGroup, setShowAddGroup] = useState(false);
  const [newGroupId, setNewGroupId] = useState("");
  const [addingGroup, setAddingGroup] = useState(false);

  // Interactive bracket state
  const [projections, setProjections] = useState<ProjectionsResponse | null>(
    null
  );
  const [overrides, setOverrides] = useState<Map<number, number>>(new Map());
  const [locks, setLocks] = useState<Map<number, string>>(new Map());
  const [simulatedProjections, setSimulatedProjections] =
    useState<ProjectionsResponse | null>(null);
  const [simulatedStandings, setSimulatedStandings] = useState<
    StandingsResult[] | null
  >(null);
  const [isSimulating, setIsSimulating] = useState(false);

  // Load groups on mount
  useEffect(() => {
    getGroups()
      .then((gs) => {
        setGroups(gs);
        if (gs.length > 0) {
          setSelectedGroupId(gs[0].group_id);
        }
      })
      .catch((err) => setError(err.message));
  }, []);

  // Load standings + projections when group changes
  useEffect(() => {
    if (!selectedGroupId) return;
    setLoading(true);
    setError(null);
    setSelectedEntryId(null);
    setSimulatedProjections(null);
    setSimulatedStandings(null);
    setOverrides(new Map());
    setLocks(new Map());

    Promise.all([getStandings(selectedGroupId), getProjections()])
      .then(([s, p]) => {
        setStandings(s);
        setProjections(p);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, [selectedGroupId]);

  const handleAddGroup = useCallback(async () => {
    const trimmed = newGroupId.trim();
    if (!trimmed) return;

    setAddingGroup(true);
    setError(null);

    try {
      const group = await addGroup("espn", trimmed);
      setGroups((prev) => {
        if (prev.find((g) => g.group_id === group.group_id)) return prev;
        return [...prev, group];
      });
      setSelectedGroupId(group.group_id);
      setNewGroupId("");
      setShowAddGroup(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add group");
    } finally {
      setAddingGroup(false);
    }
  }, [newGroupId]);

  const handleRefreshGroup = useCallback(async () => {
    if (!selectedGroupId) return;
    setLoading(true);
    setError(null);

    try {
      const updated = await refreshGroup(selectedGroupId);
      setGroups((prev) =>
        prev.map((g) => (g.group_id === updated.group_id ? updated : g))
      );
      // Re-fetch standings + projections
      const [s, p] = await Promise.all([
        getStandings(selectedGroupId),
        getProjections(),
      ]);
      setStandings(s);
      setProjections(p);
      setSimulatedProjections(null);
      setSimulatedStandings(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to refresh");
    } finally {
      setLoading(false);
    }
  }, [selectedGroupId]);

  const handleDeleteGroup = useCallback(async () => {
    if (!selectedGroupId) return;

    try {
      await deleteGroup(selectedGroupId);
      setGroups((prev) => prev.filter((g) => g.group_id !== selectedGroupId));
      setStandings(null);
      setProjections(null);
      setSelectedGroupId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete group");
    }
  }, [selectedGroupId]);

  const handleOverride = useCallback((gameId: number, probAWins: number) => {
    setOverrides((prev) => {
      const next = new Map(prev);
      next.set(gameId, probAWins);
      return next;
    });
  }, []);

  const handleLock = useCallback((gameId: number, team: string) => {
    setLocks((prev) => {
      const next = new Map(prev);
      if (team === "") {
        next.delete(gameId);
      } else {
        next.set(gameId, team);
      }
      return next;
    });
  }, []);

  const handleRun = useCallback(async () => {
    if (!selectedGroupId) return;
    setIsSimulating(true);
    setError(null);

    try {
      const locksList = Array.from(locks.entries()).map(
        ([game_id, winner]) => ({ game_id, winner })
      );
      const overridesList = Array.from(overrides.entries()).map(
        ([game_id, prob_a_wins]) => ({ game_id, prob_a_wins })
      );

      const result = await simulate({
        locks: locksList,
        probability_overrides: overridesList,
        group_id: selectedGroupId,
      });

      setSimulatedProjections({
        projections: result.projections,
        advancement: result.advancement,
        games_remaining: result.games_remaining,
        last_updated: new Date().toISOString(),
      });
      if (result.standings) {
        setSimulatedStandings(result.standings);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Simulation failed");
    } finally {
      setIsSimulating(false);
    }
  }, [selectedGroupId, locks, overrides]);

  const handleReset = useCallback(() => {
    setOverrides(new Map());
    setLocks(new Map());
    setSimulatedProjections(null);
    setSimulatedStandings(null);
  }, []);

  const hasChanges = overrides.size > 0 || locks.size > 0;
  const displayProjections = simulatedProjections || projections;
  const displayStandings = simulatedStandings || standings?.standings;

  return (
    <div className="space-y-6">
      {/* Header: Group selector + actions */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <GroupSelector
            groups={groups}
            selectedId={selectedGroupId}
            onSelect={setSelectedGroupId}
          />
          <button
            onClick={() => setShowAddGroup(!showAddGroup)}
            className="px-3 py-2 text-sm bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg transition-colors"
          >
            + Add Group
          </button>
          {selectedGroupId && (
            <>
              <button
                onClick={handleRefreshGroup}
                disabled={loading}
                className="px-3 py-2 text-sm bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-lg transition-colors disabled:opacity-50"
              >
                Refresh
              </button>
              <button
                onClick={handleDeleteGroup}
                className="px-3 py-2 text-sm bg-red-900/50 hover:bg-red-800/50 text-red-300 rounded-lg transition-colors"
              >
                Remove
              </button>
            </>
          )}
        </div>
        {standings && (
          <div className="text-xs text-gray-500">
            Updated {new Date(standings.last_updated).toLocaleString()}
          </div>
        )}
      </div>

      {/* Add Group Form */}
      {showAddGroup && (
        <div className="bg-gray-900/50 rounded-xl border border-gray-800 p-4">
          <h3 className="text-sm font-semibold text-gray-300 mb-3">
            Add ESPN Bracket Group
          </h3>
          <div className="flex items-center gap-3">
            <input
              type="text"
              value={newGroupId}
              onChange={(e) => setNewGroupId(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAddGroup()}
              placeholder="Paste ESPN group ID (e.g. 599a65bc-...)"
              className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
              disabled={addingGroup}
            />
            <button
              onClick={handleAddGroup}
              disabled={addingGroup || !newGroupId.trim()}
              className="px-4 py-2 text-sm bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg transition-colors disabled:opacity-50"
            >
              {addingGroup ? "Loading..." : "Add"}
            </button>
            <button
              onClick={() => setShowAddGroup(false)}
              className="px-3 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
            >
              Cancel
            </button>
          </div>
          <p className="text-xs text-gray-500 mt-2">
            Find your group ID in the ESPN Tournament Challenge URL after
            /group/
          </p>
        </div>
      )}

      {error && (
        <div className="bg-red-900/30 border border-red-800 rounded-lg px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {loading && (
        <div className="text-center py-12 text-gray-500">
          Running simulations...
        </div>
      )}

      {/* Interactive Bracket */}
      {displayProjections && !loading && (
        <InteractiveBracket
          projections={displayProjections}
          overrides={overrides}
          locks={locks}
          onOverride={handleOverride}
          onLock={handleLock}
          onRun={handleRun}
          onReset={handleReset}
          isSimulating={isSimulating}
          hasChanges={hasChanges}
        />
      )}

      {/* Standings Leaderboard */}
      {standings && !loading && (
        <div className="bg-gray-900/50 rounded-xl border border-gray-800 overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-800">
            <h2 className="text-lg font-semibold">
              {standings.group.group_name}
              {simulatedStandings && (
                <span className="text-sm font-normal text-blue-400 ml-2">
                  (Simulated)
                </span>
              )}
            </h2>
            <p className="text-xs text-gray-500">
              {standings.group.entry_count} entries &middot;{" "}
              {standings.games_remaining} games remaining
            </p>
          </div>
          <LeaderboardTable
            standings={displayStandings || []}
            gamesRemaining={standings.games_remaining}
            onSelectEntry={setSelectedEntryId}
          />
        </div>
      )}

      {selectedEntryId && (
        <BracketView
          entryId={selectedEntryId}
          onClose={() => setSelectedEntryId(null)}
        />
      )}

      {!standings && !loading && !error && groups.length === 0 && (
        <div className="text-center py-20">
          <h2 className="text-2xl font-bold text-gray-400 mb-2">
            March Madness Bracket Analyzer
          </h2>
          <p className="text-gray-500 mb-6">
            Add your ESPN bracket group to get started.
          </p>
          <button
            onClick={() => setShowAddGroup(true)}
            className="px-6 py-3 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg transition-colors text-lg"
          >
            + Add Your First Group
          </button>
        </div>
      )}
    </div>
  );
}
