/** API client for the FastAPI backend. */

import type {
  GroupInfo,
  GroupStandings,
  EntryDetail,
  ProjectionsResponse,
  SimulateRequest,
  SimulateResponse,
} from "./types";

const API_BASE = "/api";

async function fetchJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function getGroups(): Promise<GroupInfo[]> {
  return fetchJSON<GroupInfo[]>("/groups");
}

export async function getStandings(groupId: string): Promise<GroupStandings> {
  return fetchJSON<GroupStandings>(`/standings/${groupId}`);
}

export async function getEntryDetail(entryId: string): Promise<EntryDetail> {
  return fetchJSON<EntryDetail>(`/entries/${entryId}`);
}

export async function getProjections(): Promise<ProjectionsResponse> {
  return fetchJSON<ProjectionsResponse>("/projections");
}

export async function simulate(
  request: SimulateRequest
): Promise<SimulateResponse> {
  const res = await fetch(`${API_BASE}/projections/simulate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function addGroup(
  platform: string,
  groupId: string
): Promise<GroupInfo> {
  const res = await fetch(`${API_BASE}/groups`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ platform, group_id: groupId }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `API error: ${res.status}`);
  }
  return res.json();
}

export async function refreshGroup(groupId: string): Promise<GroupInfo> {
  const res = await fetch(`${API_BASE}/groups/${groupId}/refresh`, {
    method: "POST",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `API error: ${res.status}`);
  }
  return res.json();
}

export async function deleteGroup(groupId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/groups/${groupId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
}
