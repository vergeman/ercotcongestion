import type { StateResponse, StateRangeResponse } from './types';

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000';

export async function fetchTopology(): Promise<unknown> {
    const r = await fetch(`${BASE}/api/topology`);
    if (!r.ok) throw new Error(`topology ${r.status}`);
    return r.json();
}

export async function fetchState(ts: Date): Promise<StateResponse> {
    const r = await fetch(`${BASE}/api/state?t=${ts.toISOString()}`);
    if (!r.ok) throw new Error(`state ${r.status}`);
    return r.json();
}

export async function fetchStateRange(start: Date, end: Date): Promise<StateRangeResponse> {
    const r = await fetch(
        `${BASE}/api/state_range?start=${start.toISOString()}&end=${end.toISOString()}`
    );
    if (!r.ok) throw new Error(`state_range ${r.status}`);
    return r.json();
}
