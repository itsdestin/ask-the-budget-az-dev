import { useCallback, useEffect, useState, type ReactNode } from "react";
import * as api from "../api";
import { AdvancedPanel } from "../admin/AdvancedPanel";
import { AliasesPanel } from "../admin/AliasesPanel";
import { CorpusPanel } from "../admin/CorpusPanel";
import { CostsPanel } from "../admin/CostsPanel";
import { ExtractionChanges } from "../admin/ExtractionChanges";
import { GuidancePanel } from "../admin/GuidancePanel";
import { IssuesPanel } from "../admin/IssuesPanel";
import { NeedsAttention } from "../admin/NeedsAttention";
import { NoticesPanel } from "../admin/NoticesPanel";
import { ProviderPanel } from "../admin/ProviderPanel";
import { SaveBar } from "../admin/SaveBar";
import { describeChanges } from "../admin/changes";

// The admin surface (Plan 5 Track 1; regrouped for spec E6).
//
// The page is now FUNCTION GROUPS rather than a stack of equal panels: what
// needs attention → AI Mode → search and documents → spending → access. Eight
// full-width panels in a column read as a wall, and a new panel could only
// ever be appended to the bottom of it. A group says which question a panel
// answers before it is opened, so the page reads as a table of contents.
//
// Two structural decisions:
//
//  * ONE draft of the settings, edited locally and saved explicitly. A page
//    that saved on every keystroke would write settings.json on a network
//    share dozens of times while someone typed a username, and every write is
//    read live by every other machine in the office.
//  * The key is NEVER part of the draft. `apiKey === null` means "not
//    editing", and that sends the "__unchanged__" sentinel. Holding the key in
//    page state so a save could round-trip it is exactly the mistake the
//    sentinel exists to make impossible.

/** A labelled band of panels. The heading is the group's whole job: it names
 *  the question its panels answer, so an admin scanning the page can skip
 *  four sections without opening any of them.
 *
 *  Fix (Task 10 fix pass 2, Destin's call): `title` is optional. A group
 *  holding exactly one panel would repeat that panel's own heading right
 *  above it — "Spending" over a card titled "Spending" — which reads as the
 *  page talking to itself. Omit `title` on single-panel groups; the grouping
 *  (and its layout spacing) stays, only the redundant label goes. */
function Group({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="adm-group">
      {title ? <h2 className="adm-group-title">{title}</h2> : null}
      {children}
    </div>
  );
}

function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

type Tab = "by_user" | "by_model" | "by_tier";

export function Admin() {
  const [me, setMe] = useState<api.Me | null>(null);
  const [settings, setSettings] = useState<api.AdminSettings | null>(null);
  const [draft, setDraft] = useState<api.AdminSettings | null>(null);
  const [models, setModels] = useState<api.ModelCatalog | null>(null);
  const [tierCopy, setTierCopy] = useState<Record<string, api.AiTierInfo> | null>(null);
  const [usage, setUsage] = useState<api.AdminUsage | null>(null);
  const [corpus, setCorpus] = useState<api.AdminCorpus | null>(null);
  const [snapshots, setSnapshots] = useState<api.Snapshot[]>([]);
  const [notices, setNotices] = useState<api.Notice[]>([]);
  const [attention, setAttention] = useState<api.AttentionDocument[]>([]);
  const [swapped, setSwapped] = useState<api.SwappedDocument[]>([]);
  // Errors from Try again / Dismiss. Separate from `saveError` (the
  // settings form) and `ingestMessage` (the machine toggle) — three
  // different actions on this page, three different places a failure can
  // come from, and conflating them would attribute one action's failure to
  // another's button.
  const [attentionError, setAttentionError] = useState<string | null>(null);

  const [month, setMonth] = useState(currentMonth());
  const [tab, setTab] = useState<Tab>("by_user");
  // null = the field is untouched, so the save sends the sentinel.
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [transferTo, setTransferTo] = useState<string | null>(null);

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [restoreState, setRestoreState] = useState({
    pending: false,
    error: null as string | null,
    restored: null as string | null,
  });
  // The server's own "takes effect after a restart" sentence. Held here
  // rather than derived, because it is also where an error from the switch
  // lands — an admin who clicks and sees nothing has no way to tell a
  // silent failure from a successful one.
  const [ingestMessage, setIngestMessage] = useState<string | null>(null);

  const loadModels = useCallback(async (refresh = false) => {
    try {
      setModels(await api.adminModels(refresh));
    } catch {
      // The catalog is the one panel that degrades to "type an id yourself".
      // Failing the whole page over it would be worse than losing the picker.
      setModels(null);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const who = await api.me();
        if (cancelled) return;
        setMe(who);
        if (!who.is_admin) {
          setLoading(false);
          return;
        }
        const [s, u, c, b, n, a] = await Promise.all([
          api.adminSettings(),
          api.adminUsage(month),
          api.adminCorpus(),
          api.adminBackups(),
          api.adminNotices(),
          api.adminAttention(),
        ]);
        if (cancelled) return;
        setSettings(s);
        setDraft(s);
        setUsage(u);
        setCorpus(c);
        setSnapshots(b.snapshots);
        setNotices(n.notices);
        setAttention(a.documents);
        setSwapped(a.swapped ?? []);
        // The initial load can fail to even read the jobs directory (a
        // share that's gone away) — surfaced through the SAME error slot
        // the retry/dismiss actions already use below, rather than a
        // second message a reader would have to learn to recognise.
        if (a.error) setAttentionError(a.error);
        // These two are allowed to fail without taking the page down.
        api.aiStatus().then((st) => !cancelled && setTierCopy(st.tiers)).catch(() => {});
        loadModels();
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // `month` deliberately excluded — changing it refetches usage only, below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!me?.is_admin) return;
    let cancelled = false;
    api
      .adminUsage(month)
      .then((u) => !cancelled && setUsage(u))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [month, me]);

  async function save() {
    if (!draft) return;
    setSaveError(null);
    setSaved(false);
    setSaving(true);
    try {
      const body: api.AdminSettingsWrite = {
        provider: {
          provider: draft.provider.provider,
          base_url: draft.provider.base_url,
          // Always sent, including as nulls: the server treats an explicit
          // null as "clear this price", which is how switching back to
          // OpenRouter drops rates that no longer apply. Omitting them
          // would leave a stale custom price attached to an OpenRouter
          // config, where it means nothing but reads as if it does.
          prompt_usd_per_m: draft.provider.prompt_usd_per_m,
          completion_usd_per_m: draft.provider.completion_usd_per_m,
        },
        tiers: draft.tiers,
        ai_enabled: draft.ai_enabled,
        default_monthly_limit_usd: draft.default_monthly_limit_usd,
        user_limits: draft.user_limits,
        exempt_users: draft.exempt_users,
        // The sentinel when the field was never touched. This is the whole
        // point of the field: an admin editing a spend limit must not be able
        // to blank the key by saving the form.
        api_key: apiKey === null ? api.UNCHANGED_KEY : apiKey,
      };
      if (transferTo !== null) {
        body.admin_username = transferTo;
        body.confirm_admin_transfer = true;
      }
      const next = await api.saveAdminSettings(body);
      setSettings(next);
      setDraft(next);
      setApiKey(null);
      setTransferTo(null);
      setSaved(true);
    } catch (err) {
      // The server's own sentence. It is written for this reader and is more
      // specific than anything this component could infer.
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  /** Throw away every pending edit and go back to what is on disk. The
   *  counterpart to naming the changes: an admin who reads the list and
   *  decides they did not mean any of it needs one click, not a reload. */
  function discard() {
    if (!settings) return;
    setDraft(settings);
    setApiKey(null);
    setTransferTo(null);
    setSaveError(null);
    setSaved(false);
  }

  async function restore(name: string) {
    setRestoreState({ pending: true, error: null, restored: null });
    try {
      const result = await api.restoreBackup(name);
      setRestoreState({ pending: false, error: null, restored: result.restored });
    } catch (err) {
      setRestoreState({
        pending: false,
        error: err instanceof Error ? err.message : String(err),
        restored: null,
      });
    }
  }

  // Try again / Dismiss both reuse the existing job actions (T8: a
  // held-back document is an ordinary `failed` job, no new state) — see
  // the WHY comment on the `failed -> cancelled` branch in
  // ingest/jobs.py::advance() for why Dismiss's cancel call is legal at
  // all. Re-reads BOTH the attention list and the corpus queue counts
  // rather than patching local state: a retry moves a document out of
  // this panel and into the queue CorpusPanel already shows, and guessing
  // that transition client-side is how the two panels end up disagreeing.
  async function attentionAction(kind: "retry" | "dismiss", jobId: string) {
    try {
      if (kind === "retry") await api.retryJob(jobId);
      else await api.cancelJob(jobId);
      const [a, c] = await Promise.all([api.adminAttention(), api.adminCorpus()]);
      setAttention(a.documents);
      setSwapped(a.swapped ?? []);
      setCorpus(c);
      // A success after an earlier failure must clear the old message -- an
      // admin who retries after a network hiccup and succeeds should not
      // still see "The queue could not be reached" beside a panel that just
      // worked (the same stuck-stale-mark shape the chat-history citation
      // chips were fixed for).
      setAttentionError(null);
    } catch (err) {
      setAttentionError(err instanceof Error ? err.message : String(err));
    }
  }

  async function setIngestHere(enabled: boolean) {
    try {
      const result = await api.adminSetMachineIngest(enabled);
      setIngestMessage(result.message);
      // Re-read rather than patching local state: the queue-stalled warning
      // is the SERVER's decision (queued > 0, nothing running, ingest off
      // here), so guessing it client-side is how the toggle and the warning
      // end up disagreeing on screen.
      setCorpus(await api.adminCorpus());
    } catch (err) {
      setIngestMessage(err instanceof Error ? err.message : String(err));
    }
  }

  if (loading) {
    return (
      <main className="page-admin" data-testid="admin">
        <div className="wrap">
          <p className="adm-empty">Loading…</p>
        </div>
      </main>
    );
  }

  if (me && !me.is_admin) {
    return (
      <main className="page-admin" data-testid="admin">
        <div className="wrap">
          <section className="card adm-panel">
            <h1>Admin</h1>
            <p>
              This page is limited to {me.admin_username || "whoever claims it"}.
              Ask them if you need something changed.
            </p>
          </section>
        </div>
      </main>
    );
  }

  if (loadError || !draft || !usage || !corpus || !me) {
    return (
      <main className="page-admin" data-testid="admin">
        <div className="wrap">
          <section className="card adm-panel">
            <h1>Admin</h1>
            <p className="adm-warn" role="alert">
              {loadError ?? "This page could not load."}
            </p>
          </section>
        </div>
      </main>
    );
  }

  // Named so the save bar can say what is pending. Labels come from
  // /api/ai/status so the answer modes are called what the rest of the app
  // calls them.
  const changes = describeChanges(
    settings,
    draft,
    apiKey,
    transferTo,
    Object.fromEntries(
      Object.entries(tierCopy ?? {}).map(([tier, info]) => [tier, info.label]),
    ),
  );

  return (
    <main className="page-admin" data-testid="admin">
      <div className="wrap">
        <h1>Admin</h1>

        {/* Anything wrong goes FIRST. NoticesPanel disappears entirely when
            there is nothing — a panel that is present every day gets scrolled
            past — but the issue inbox stays, because an analyst was told
            their report would be seen and the door needs a visible other
            end. */}
        <Group title="Needs attention">
          {/* Held-out documents lead this group (merge with master,
              2026-08-13). Plan B agreed a standalone panel "above Corpus
              health"; master has since created this group for exactly this
              purpose, and TWO surfaces both titled "Needs attention" would
              have been worse than either. It leads because a document held
              out of search is the only item here that means the corpus is
              currently missing content an analyst will look for.
              Renders nothing at all when nothing has failed. */}
          <NeedsAttention
            documents={attention}
            onRetry={(jobId) => void attentionAction("retry", jobId)}
            onDismiss={(jobId) => void attentionAction("dismiss", jobId)}
          />
          {attentionError ? (
            <p className="adm-warn" role="alert" data-testid="admin-attention-error">
              {attentionError}
            </p>
          ) : null}
          <NoticesPanel notices={notices} />
          <IssuesPanel />
        </Group>

        {/* Group always paints its own <h2>, even with no children (see
            `function Group` above) -- so wrapping ExtractionChanges
            unconditionally would put a permanent "Extraction method
            changed" heading over an empty section on every ordinary day,
            which is exactly the scroll-past habit the global no-swaps
            rule exists to prevent. The whole group is gated on the same
            condition ExtractionChanges checks internally, so a normal day
            with nothing swapped shows nothing here at all. */}
        {swapped.length > 0 ? (
          <Group title="Extraction method changed">
            <ExtractionChanges documents={swapped} />
          </Group>
        ) : null}

        <Group title="AI Mode">
          {/* AI Mode is one section now: key, models, spending limits and which
              service, in that order of how often they are touched. They used to
              be three panels, which put a spending cap several screens away
              from the model choice that drives it. */}
          <ProviderPanel
            settings={draft}
            models={models}
            tierCopy={tierCopy}
            apiKey={apiKey}
            onApiKeyChange={setApiKey}
            onAiEnabledChange={(ai_enabled) => setDraft({ ...draft, ai_enabled })}
            onTierEnabledChange={(tier, enabled) =>
              setDraft({
                ...draft,
                // Spread the existing tier: switching a mode off must keep the
                // model it was using, or turning it back on becomes a fresh
                // decision the admin already made once.
                tiers: { ...draft.tiers, [tier]: { ...draft.tiers[tier], enabled } },
              })
            }
            onProviderChange={(provider) =>
              setDraft({ ...draft, provider: { ...draft.provider, provider } })
            }
            onBaseUrlChange={(base_url) =>
              setDraft({ ...draft, provider: { ...draft.provider, base_url } })
            }
            onPriceChange={(field, value) =>
              setDraft({ ...draft, provider: { ...draft.provider, [field]: value } })
            }
            onTierModelChange={(tier, model) =>
              setDraft({
                ...draft,
                tiers: { ...draft.tiers, [tier]: { ...draft.tiers[tier], model } },
              })
            }
            onRefreshModels={() => loadModels(true)}
            limitsActive={usage.limits_active}
            limitsInactiveReason={usage.limits_inactive_reason}
            onDefaultChange={(default_monthly_limit_usd) =>
              setDraft({ ...draft, default_monthly_limit_usd })
            }
            onUserLimitsChange={(user_limits) => setDraft({ ...draft, user_limits })}
            onExemptChange={(exempt_users) => setDraft({ ...draft, exempt_users })}
          />
          <GuidancePanel />
        </Group>

        <Group title="Search & documents">
          <CorpusPanel
            corpus={corpus}
            snapshots={snapshots}
            onRestore={restore}
            restoreState={restoreState}
            onSetIngest={setIngestHere}
            ingestMessage={ingestMessage}
          />
          <AliasesPanel />
        </Group>

        {/* No title: this group holds only CostsPanel, whose own heading is
            "Spending" (Task 10 fix pass 2, Destin's call). */}
        <Group>
          <CostsPanel
            usage={usage}
            month={month}
            onMonthChange={setMonth}
            tab={tab}
            onTabChange={setTab}
            isCustomEndpoint={draft.provider.provider === "custom"}
          />
        </Group>

        {/* No title: this group holds only AdvancedPanel, whose own heading
            is "Access and files" (Task 10 fix pass 2, Destin's call). */}
        <Group>
          <AdvancedPanel
            settings={settings ?? draft}
            me={me}
            dataDir={corpus.data_dir}
            onTransfer={(username) => {
              setTransferTo(username);
              setDraft({ ...draft, admin_username: username });
            }}
          />
        </Group>

        {/* The settings save confirmation, kept at the bottom of the page
            beside the sticky bar that triggers it — the admin's eye is there,
            not at a heading five groups up. */}
        {saved ? (
          <p className="adm-ok" role="status" data-testid="admin-saved">
            Saved. Every machine picks this up without restarting.
          </p>
        ) : null}
      </div>

      {/* Outside the .wrap so it can stick to the viewport rather than to a
          point in the page. It renders nothing at all when there is nothing
          pending — the reason the old button was confusing is that it was
          always there, saying the same thing, attached to no one card. */}
      <SaveBar
        changes={changes}
        onSave={save}
        onDiscard={discard}
        saving={saving}
        error={saveError}
      />
    </main>
  );
}
