import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { AdminPanel } from "./components/AdminPanel";
import { Conversation } from "./components/Conversation";
import { Header } from "./components/Header";
import { ImpactMap } from "./components/ImpactMap";
import { SidePanel } from "./components/SidePanel";
import { WorkPanel } from "./components/WorkPanel";
import { selectionFrom } from "./mapView";
import type { AppState, MapData, Persona } from "./types";

const PERSONA_KEY = "proactive.persona";
const SLOW_MS = 30_000; // 合図がなくても 30 秒ごとに読み直す（決定 9）
const FAST_MS = 3_000; // チャットの返事待ちのあいだ
const DEBOUNCE_MS = 500;
const RECONNECT_MS = 10_000;

function loadPersona(): string {
  try {
    return localStorage.getItem(PERSONA_KEY) || "tanaka";
  } catch {
    return "tanaka";
  }
}

function savePersona(id: string) {
  try {
    localStorage.setItem(PERSONA_KEY, id);
  } catch {
    /* 保存できなくても動く */
  }
}

export function App() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [persona, setPersona] = useState(loadPersona);
  const [map, setMap] = useState<MapData | null>(null);
  const [state, setState] = useState<AppState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [adminOpen, setAdminOpen] = useState(false);
  const debounce = useRef<number | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      setState(await api.state(persona));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [persona]);

  const refreshSoon = useCallback(() => {
    window.clearTimeout(debounce.current);
    debounce.current = window.setTimeout(() => {
      refresh();
      api.map().then(setMap).catch(() => undefined);
    }, DEBOUNCE_MS);
  }, [refresh]);

  useEffect(() => {
    api
      .me()
      .then((me) => {
        setPersonas(me.personas);
        if (!me.personas.some((p) => p.id === persona)) setPersona(me.personas[0]?.id ?? "tanaka");
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    api.map().then(setMap).catch((e) => setError(e instanceof Error ? e.message : String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setSelected(null);
    refresh();
  }, [refresh]);

  useEffect(() => {
    const timer = window.setInterval(refresh, state?.chat_busy ? FAST_MS : SLOW_MS);
    return () => window.clearInterval(timer);
  }, [refresh, state?.chat_busy]);

  // 画面への合図（Web PubSub）。届いたら読み直す。切れたらつなぎ直す
  useEffect(() => {
    let socket: WebSocket | null = null;
    let closed = false;
    let retry: number | undefined;
    const connect = async () => {
      try {
        const { url } = await api.negotiate(persona);
        if (!url || closed) return;
        socket = new WebSocket(url);
        socket.onmessage = () => refreshSoon();
        socket.onclose = () => {
          if (!closed) retry = window.setTimeout(connect, RECONNECT_MS);
        };
      } catch {
        if (!closed) retry = window.setTimeout(connect, RECONNECT_MS);
      }
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(retry);
      socket?.close();
    };
  }, [persona, refreshSoon]);

  const selection = useMemo(() => {
    const n = selected && state ? state.notifications[selected] : undefined;
    return n ? selectionFrom(n) : null;
  }, [selected, state]);

  function changePersona(id: string) {
    savePersona(id);
    setPersona(id);
  }

  return (
    <div className="app">
      <Header
        state={state}
        personas={personas}
        persona={persona}
        onPersona={changePersona}
        adminOpen={adminOpen}
        onToggleAdmin={() => setAdminOpen(!adminOpen)}
      />
      {error && <div className="error banner">{error}</div>}
      {adminOpen && <AdminPanel onChanged={refreshSoon} />}
      {state ? (
        <main className="panes">
          <Conversation
            state={state}
            persona={persona}
            selectedNotification={selected}
            onSelect={setSelected}
            onChanged={refresh}
          />
          <section className="pane center">
            <h2>影響マップ{selection ? "（選んだ通知の影響を表示中）" : ""}</h2>
            {map && <ImpactMap map={map} selection={selection} view={{ team: state.team, chief: state.team === "chief_engineer" }} />}
            <WorkPanel state={state} />
          </section>
          <SidePanel state={state} persona={persona} onChanged={refresh} />
        </main>
      ) : (
        !error && <div className="loading">読み込んでいます…</div>
      )}
    </div>
  );
}
