import { useCallback, useEffect, useState } from "react";
import * as api from "../api";
import { CorpusPanel } from "../admin/CorpusPanel";
import { CostsPanel } from "../admin/CostsPanel";
import { LimitsPanel } from "../admin/LimitsPanel";
import { NoticesPanel } from "../admin/NoticesPanel";
import { ProviderPanel } from "../admin/ProviderPanel";
import { TransferPanel } from "../admin/TransferPanel";

// The admin surface (Plan 5 Track 1).
//
// Panel order is the order a new admin needs them, not the order they were
// built: what is this costing → how do I turn AI Mode on → who can spend what
// → is the corpus healthy → what broke → who holds this page → where does
// everything live.
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

  const [month, setMonth] = useState(currentMonth());
  const [tab, setTab] = useState<Tab>("by_user");
  // null = the field is untouched, so the save sends the sentinel.
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [transferTo, setTransferTo] = useState<string | null>(null);

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [restoreState, setRestoreState] = useState({
    pending: false,
    error: null as string | null,
    restored: null as string | null,
  });

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
        const [s, u, c, b, n] = await Promise.all([
          api.adminSettings(),
          api.adminUsage(month),
          api.adminCorpus(),
          api.adminBackups(),
          api.adminNotices(),
        ]);
        if (cancelled) return;
        setSettings(s);
        setDraft(s);
        setUsage(u);
        setCorpus(c);
        setSnapshots(b.snapshots);
        setNotices(n.notices);
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
    try {
      const body: api.AdminSettingsWrite = {
        provider: {
          provider: draft.provider.provider,
          base_url: draft.provider.base_url,
        },
        tiers: draft.tiers,
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
    }
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

  return (
    <main className="page-admin" data-testid="admin">
      <div className="wrap">
        <h1>Admin</h1>

        <CostsPanel
          usage={usage}
          month={month}
          onMonthChange={setMonth}
          tab={tab}
          onTabChange={setTab}
        />

        <ProviderPanel
          settings={draft}
          models={models}
          tierCopy={tierCopy}
          apiKey={apiKey}
          onApiKeyChange={setApiKey}
          onProviderChange={(provider) =>
            setDraft({ ...draft, provider: { ...draft.provider, provider } })
          }
          onBaseUrlChange={(base_url) =>
            setDraft({ ...draft, provider: { ...draft.provider, base_url } })
          }
          onTierModelChange={(tier, model) =>
            setDraft({ ...draft, tiers: { ...draft.tiers, [tier]: { model } } })
          }
          onRefreshModels={() => loadModels(true)}
        />

        <LimitsPanel
          settings={draft}
          limitsActive={usage.limits_active}
          limitsInactiveReason={usage.limits_inactive_reason}
          onDefaultChange={(default_monthly_limit_usd) =>
            setDraft({ ...draft, default_monthly_limit_usd })
          }
          onUserLimitsChange={(user_limits) => setDraft({ ...draft, user_limits })}
          onExemptChange={(exempt_users) => setDraft({ ...draft, exempt_users })}
        />

        <div className="adm-save">
          <button type="button" className="adm-btn" onClick={save} data-testid="admin-save">
            Save changes
          </button>
          {saved ? (
            <span className="adm-ok" role="status" data-testid="admin-saved">
              Saved. Every machine picks this up without restarting.
            </span>
          ) : null}
          {saveError ? (
            <span className="adm-warn" role="alert" data-testid="admin-save-error">
              {saveError}
            </span>
          ) : null}
        </div>

        <CorpusPanel
          corpus={corpus}
          snapshots={snapshots}
          onRestore={restore}
          restoreState={restoreState}
        />

        <NoticesPanel notices={notices} />

        <TransferPanel
          settings={settings ?? draft}
          me={me}
          onTransfer={(username) => {
            setTransferTo(username);
            setDraft({ ...draft, admin_username: username });
          }}
        />

        <section className="card adm-panel" data-testid="admin-locations">
          <h2>Where things live</h2>
          <dl className="adm-stats">
            <div>
              <dt>Shared data folder</dt>
              <dd>
                <code>{corpus.data_dir}</code>
              </dd>
            </div>
            <div>
              <dt>Settings file</dt>
              <dd>
                <code>{corpus.data_dir}/settings.json</code>
              </dd>
            </div>
            <div>
              <dt>Spending records</dt>
              <dd>
                <code>{corpus.data_dir}/usage/</code>
              </dd>
            </div>
            <div>
              <dt>Snapshots</dt>
              <dd>
                <code>{corpus.data_dir}/backups/</code>
              </dd>
            </div>
            <div>
              <dt>Your OpenRouter account</dt>
              <dd>
                <a href="https://openrouter.ai/settings/credits" target="_blank" rel="noreferrer">
                  openrouter.ai — credits and the hard monthly cap
                </a>
              </dd>
            </div>
          </dl>
        </section>
      </div>
    </main>
  );
}
