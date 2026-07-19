import React, { useEffect, useState, useCallback, useRef } from "react";
import { api, fileUrl, thumbUrl } from "./api.js";
import ClipDetail from "./ClipDetail.jsx";
import Timeline from "./Timeline.jsx";
import CardCaption from "./CardCaption.jsx";

// The links-only cloud organizer (GitHub Pages). "Update for cloud" opens it
// automatically after writing the backup so syncing is one press, not two apps.
const CLOUD_URL = "https://brainpulp.github.io/reeler/";

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
  const [cloudReady, setCloudReady] = useState(false); // show cloud link in banner
  const [sniff, setSniff] = useState(null); // background sniff progress
  const [scan, setScan] = useState(null); // background library-scan progress
  const [backfill, setBackfill] = useState(null); // collection backfill progress
  const [index, setIndex] = useState(null); // metadata-index progress
  const pollRef = useRef(null);
  const exportAfterRef = useRef(false); // download the cloud file once a sync finishes

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
        const [sp, scp, bf, ix] = await Promise.all([
          api.sniffProgress(),
          api.scanProgress(),
          api.collectionsProgress(),
          api.indexProgress(),
        ]);
        setSniff(sp);
        setScan(scp);
        setBackfill(bf);
        setIndex(ix);
        await refresh();
        if (!sp.running && !scp.running && !bf.running && !ix.running) {
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
            if (!bf.error && exportAfterRef.current) {
              const a = document.createElement("a");
              a.href = "/api/export/cloud";
              a.download = "reeler-cloud-backup.json";
              document.body.appendChild(a);
              a.click();
              a.remove();
              // Open the cloud organizer so the user just clicks Import / Sync
              // there. Popup blockers may stop this (it's not a direct click);
              // the banner link below is the fallback.
              window.open(CLOUD_URL, "_blank", "noopener");
              setCloudReady(true);
              setInfo(
                `Updated ${bf.added} reels · saved reeler-cloud-backup.json. Opened the cloud app — click "Import / Sync" and pick that file.`
              );
            } else {
              setInfo(
                bf.error
                  ? `Update stopped: ${bf.error}`
                  : `Organized ${bf.added} reels into collections`
              );
            }
            exportAfterRef.current = false;
          } else if (ix.done) {
            setInfo(
              ix.error
                ? `Index stopped: ${ix.error}`
                : `${ix.capped ? "Indexed a batch" : "Index done"} — ${ix.added} reels catalogued${ix.capped ? " (run again for more)" : ""}`
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

  // One click: run the light collection update, then auto-download the cloud file.
  const onUpdateForCloud = async () => {
    exportAfterRef.current = true;
    await onBackfill();
  };

  const onIndex = async () => {
    setError(null);
    try {
      const p = await api.startIndex();
      setIndex(p);
      startPolling();
    } catch (e) {
      setError(e.message);
    }
  };

  const onClean = () =>
    run(async () => {
      const r = await api.cleanLibrary();
      setInfo(`Freed ${r.freed} temporary working file${r.freed === 1 ? "" : "s"}`);
    });

  // On load, reconnect to any job already running (sniff crawl or the
  // startup library scan) so the grid fills in live.
  useEffect(() => {
    Promise.all([
      api.sniffProgress(),
      api.scanProgress(),
      api.collectionsProgress(),
      api.indexProgress(),
    ])
      .then(([sp, scp, bf, ix]) => {
        setSniff(sp);
        setScan(scp);
        setBackfill(bf);
        setIndex(ix);
        if (sp.running || scp.running || bf.running || ix.running) startPolling();
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
            {index && index.running ? (
              <span className="sniff-progress">cataloguing… {index.added}</span>
            ) : (
              <button
                onClick={onIndex}
                disabled={!(ig && ig.connected)}
                title="Catalog saved reels (metadata + thumbnails only, no videos)"
              >
                Index saved reels
              </button>
            )}
            {backfill && backfill.running ? (
              <span className="sniff-progress">
                updating… {backfill.added} sorted
              </span>
            ) : (
              <button
                className="primary"
                onClick={onUpdateForCloud}
                disabled={!(ig && ig.connected)}
                title="Light update from Instagram (recent additions only), then download the file for the cloud app"
              >
                ⟳ Update for cloud
              </button>
            )}
            <button onClick={onClean} disabled={busy} title="Delete temporary working videos (keeps saved + exports)">
              Free space
            </button>
            <a
              className="upload-btn"
              href="/api/export/cloud"
              download="reeler-cloud-backup.json"
              title="Download a file to Import/Sync into the cloud app"
            >
              Export for cloud
            </a>
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
        <div className="info-banner">
          <span onClick={() => setInfo(null)}>{info}</span>
          {cloudReady && (
            <a
              href={CLOUD_URL}
              target="_blank"
              rel="noopener noreferrer"
              style={{ marginLeft: 8, fontWeight: 600 }}
            >
              Open cloud app ↗
            </a>
          )}
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
                ) : c.thumb_url ? (
                  <img
                    src={c.thumb_url}
                    alt=""
                    loading="lazy"
                    referrerPolicy="no-referrer"
                  />
                ) : c.has_video ? (
                  <video src={fileUrl(c.id)} muted />
                ) : (
                  <div className="noimg">▶</div>
                )}
                {c.duration ? (
                  <span className="dur">{c.duration.toFixed(1)}s</span>
                ) : null}
                {!c.has_video && (
                  <span className="badge-indexed" title="indexed — not downloaded">
                    ⤓
                  </span>
                )}
                {c.kept ? <span className="badge-kept" title="saved">★</span> : null}
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
