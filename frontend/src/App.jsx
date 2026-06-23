import React, { useEffect, useState, useCallback, useRef } from "react";
import { api, fileUrl, thumbUrl } from "./api.js";
import ClipDetail from "./ClipDetail.jsx";
import Timeline from "./Timeline.jsx";
import CardCaption from "./CardCaption.jsx";

export default function App() {
  const [clips, setClips] = useState([]);
  const [tags, setTags] = useState([]);
  const [collections, setCollections] = useState([]);
  const [activeTag, setActiveTag] = useState(null);
  const [activeCollection, setActiveCollection] = useState(null);
  const [selected, setSelected] = useState([]); // ids picked for combine
  const [open, setOpen] = useState(null); // clip in detail view
  const [timeline, setTimeline] = useState([]); // ordered combine items
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [ig, setIg] = useState(null); // instagram connection status
  const [info, setInfo] = useState(null); // transient success message
  const [sniff, setSniff] = useState(null); // background sniff progress
  const [scan, setScan] = useState(null); // background library-scan progress
  const [backfill, setBackfill] = useState(null); // collection backfill progress
  const pollRef = useRef(null);

  const addToTimeline = (item) => setTimeline((t) => [...t, item]);

  const refresh = useCallback(async () => {
    const data = await api.listClips(activeTag, activeCollection);
    setClips(data.clips);
    setTags(data.tags);
    setCollections(data.collections || []);
  }, [activeTag, activeCollection]);

  const checkIg = useCallback(() => {
    api.igStatus().then(setIg).catch(() => setIg({ connected: false }));
  }, []);

  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, [refresh]);

  useEffect(() => {
    checkIg();
  }, [checkIg]);

  const run = async (fn) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  // Poll both background jobs, refresh the grid as clips arrive, stop when idle.
  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      try {
        const [sp, scp, bf] = await Promise.all([
          api.sniffProgress(),
          api.scanProgress(),
          api.collectionsProgress(),
        ]);
        setSniff(sp);
        setScan(scp);
        setBackfill(bf);
        await refresh();
        if (!sp.running && !scp.running && !bf.running) {
          clearInterval(pollRef.current);
          pollRef.current = null;
          if (sp.done) {
            const how = sp.stopped
              ? "Stopped"
              : sp.capped
              ? "Safe batch limit reached — run again later for more"
              : "Done";
            setInfo(
              sp.error
                ? `Sniff stopped: ${sp.error}`
                : `${how} — ${sp.added} new, ${sp.skipped} already had`
            );
          } else if (bf.done) {
            setInfo(
              bf.error
                ? `Backfill stopped: ${bf.error}`
                : `Organized ${bf.added} reels into collections`
            );
          }
        }
      } catch {
        /* transient; keep polling */
      }
    }, 2500);
  }, [refresh]);

  const onSniff = async () => {
    setError(null);
    try {
      const p = await api.startSniff();
      setSniff(p);
      startPolling();
    } catch (e) {
      setError(e.message);
    }
  };

  const onStopSniff = async () => {
    try {
      const p = await api.stopSniff();
      setSniff(p);
    } catch (e) {
      setError(e.message);
    }
  };

  const onBackfill = async () => {
    setError(null);
    try {
      const p = await api.backfillCollections();
      setBackfill(p);
      startPolling();
    } catch (e) {
      setError(e.message);
    }
  };

  // On load, reconnect to any job already running (sniff crawl or the
  // startup library scan) so the grid fills in live.
  useEffect(() => {
    Promise.all([
      api.sniffProgress(),
      api.scanProgress(),
      api.collectionsProgress(),
    ])
      .then(([sp, scp, bf]) => {
        setSniff(sp);
        setScan(scp);
        setBackfill(bf);
        if (sp.running || scp.running || bf.running) startPolling();
      })
      .catch(() => {});
    return () => pollRef.current && clearInterval(pollRef.current);
  }, [startPolling]);

  const onUpload = (e) => {
    const file = e.target.files?.[0];
    if (file) run(() => api.upload(file));
    e.target.value = "";
  };

  const toggleSelect = (id) =>
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  // Drop the selected clips into the timeline as full-length segments.
  const onAddSelected = () => {
    const byId = Object.fromEntries(clips.map((c) => [c.id, c]));
    selected.forEach((id) => {
      const c = byId[id];
      if (!c) return;
      addToTimeline({
        kind: "segment",
        clip_id: id,
        start: 0,
        end: c.duration || 0,
        label: c.title || (c.ig_owner ? `@${c.ig_owner}` : c.filename),
      });
    });
    setSelected([]);
  };

  return (
    <div className="app">
      <header>
        <h1>🎬 Reeler</h1>
        <div className="toolbar">
          {ig && (
            <span
              className={"ig-badge " + (ig.connected ? "ok" : "off")}
              title={ig.connected ? `signed in as @${ig.username}` : ig.error || "not connected"}
            >
              {ig.connected ? `● @${ig.username}` : "○ instagram"}
            </span>
          )}
          <span className="sniff-group">
            {scan && scan.running && (
              <span className="sniff-progress">
                importing {scan.added} from disk…
              </span>
            )}
            {sniff && sniff.running ? (
              <>
                <button className="stop" onClick={onStopSniff}>
                  ■ Stop sniff
                </button>
                <span className="sniff-progress">
                  {sniff.added} new · {sniff.skipped} skipped
                </span>
              </>
            ) : (
              <button onClick={onSniff} disabled={!(ig && ig.connected)}>
                Sniff saved reels
              </button>
            )}
            {backfill && backfill.running ? (
              <span className="sniff-progress">
                organizing… {backfill.added} sorted
              </span>
            ) : (
              <button
                onClick={onBackfill}
                disabled={!(ig && ig.connected)}
                title="Map your Instagram collections onto downloaded reels (no re-downloads)"
              >
                Organize by collection
              </button>
            )}
          </span>
          <label className="upload-btn">
            Import file
            <input type="file" accept="video/*" hidden onChange={onUpload} />
          </label>
          <button
            onClick={onAddSelected}
            disabled={busy || selected.length === 0}
            title="Add selected clips to the timeline as full segments"
          >
            Add selected → timeline ({selected.length})
          </button>
        </div>
      </header>

      {error && <div className="error">⚠ {error}</div>}
      {info && (
        <div className="info-banner" onClick={() => setInfo(null)}>
          {info}
        </div>
      )}

      <div className="tagbar">
        <button
          className={!activeTag ? "tag active" : "tag"}
          onClick={() => setActiveTag(null)}
        >
          all
        </button>
        {tags.map((t) => (
          <button
            key={t}
            className={activeTag === t ? "tag active" : "tag"}
            onClick={() => setActiveTag(t)}
          >
            #{t}
          </button>
        ))}
      </div>

      {collections.length > 0 && (
        <div className="tagbar collbar">
          <span className="collbar-label">📁</span>
          <button
            className={!activeCollection ? "tag active" : "tag"}
            onClick={() => setActiveCollection(null)}
          >
            all
          </button>
          {collections.map((c) => (
            <button
              key={c}
              className={activeCollection === c ? "tag active" : "tag"}
              onClick={() => setActiveCollection(c)}
            >
              {c}
            </button>
          ))}
        </div>
      )}

      {clips.length === 0 ? (
        <div className="empty">
          No clips yet. Sniff your saved reels or import a file to begin.
        </div>
      ) : (
        <div className="grid">
          {clips.map((c) => (
            <div
              key={c.id}
              className={
                "card" +
                (selected.includes(c.id) ? " sel" : "") +
                (c.source === "derived" ? " derived" : "")
              }
            >
              <div className="thumb" onClick={() => setOpen(c)}>
                {c.thumb_rel ? (
                  <img src={thumbUrl(c.id)} alt="" loading="lazy" />
                ) : (
                  <video src={fileUrl(c.id)} muted />
                )}
                <span className="dur">
                  {c.duration ? `${c.duration.toFixed(1)}s` : ""}
                </span>
              </div>
              <CardCaption clip={c} onChanged={refresh} />
              <div className="meta">
                <span className="owner">
                  {c.source === "derived"
                    ? `↳ ${c.op?.type || "edit"}`
                    : c.ig_owner
                    ? `@${c.ig_owner}`
                    : c.filename}
                </span>
                <input
                  type="checkbox"
                  checked={selected.includes(c.id)}
                  onChange={() => toggleSelect(c.id)}
                  title="select for combine"
                />
              </div>
              {c.tags.length > 0 && (
                <div className="cardtags">
                  {c.tags.map((t) => (
                    <span key={t} className="minitag">
                      #{t}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {open && (
        <ClipDetail
          clip={open}
          onClose={() => setOpen(null)}
          onAddToTimeline={addToTimeline}
          onChanged={async () => {
            await refresh();
          }}
        />
      )}

      <Timeline items={timeline} setItems={setTimeline} onRendered={refresh} />
    </div>
  );
}
