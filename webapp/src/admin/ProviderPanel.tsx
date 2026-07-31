import * as api from "../api";
import { perMillion } from "./format";

// AI Mode setup: where calls go, the key, and which model each answer mode
// uses.
//
// The API key is the delicate part and it is delicate in BOTH directions. The
// field renders EMPTY with a last-four hint beside it — the server never sends
// the key, so there is nothing to prefill and nothing to leak into a
// screenshot. And a form submitted without touching that field sends the
// literal "__unchanged__" rather than "", because "" is a real edit meaning
// "turn AI Mode off" and a form that blanked the key by accident would look
// like "AI Mode randomly stopped working" a week later.

/** S15's caveats, rendered IN the panel rather than in the handbook.
 *  An admin choosing this option is leaving the supported path, and the
 *  moment to say so is while they are choosing. */
const CUSTOM_CAVEATS = [
  "Per-person costs stop being dollar figures — this app only sees token counts, so spend limits stop being enforced.",
  "There is no model list, no recommendations and no live pricing. You type the model id your endpoint expects.",
  "The model must support tool calling. AI Mode calls a search tool before every answer, so a model without it fails every question rather than answering worse.",
  "This is self-support territory. If answers stop working, the app can only show you what your endpoint returned.",
];

function ModelOption({ card }: { card: api.ModelCard }) {
  // A model the live catalog could not confirm is kept and disabled, never
  // dropped: an admin whose tier names a retired model needs to SEE that,
  // not find an unexplained gap where their choice used to be.
  const label = card.available
    ? `${card.name} — ${perMillion(card.prompt_usd_per_m)} in, ${perMillion(card.completion_usd_per_m)} out`
    : `${card.name} — no longer offered by OpenRouter`;
  return (
    <option value={card.id} disabled={!card.available}>
      {label}
    </option>
  );
}

export function ProviderPanel({
  settings,
  models,
  tierCopy,
  apiKey,
  onApiKeyChange,
  onProviderChange,
  onBaseUrlChange,
  onTierModelChange,
  onRefreshModels,
}: {
  settings: api.AdminSettings;
  models: api.ModelCatalog | null;
  /** `/api/ai/status`'s tiers. The explainer sentences are rendered from
   *  THESE — server-side copy (S16), so the admin page and the composer
   *  cannot drift. Nothing here re-types them. */
  tierCopy: Record<string, api.AiTierInfo> | null;
  apiKey: string | null;
  onApiKeyChange: (value: string | null) => void;
  onProviderChange: (provider: "openrouter" | "custom") => void;
  onBaseUrlChange: (value: string) => void;
  onTierModelChange: (tier: string, model: string) => void;
  onRefreshModels: () => void;
}) {
  const isCustom = settings.provider.provider === "custom";
  const editingKey = apiKey !== null;

  return (
    <section className="card adm-panel" aria-labelledby="adm-ai-h" data-testid="admin-provider">
      <h2 id="adm-ai-h">AI Mode setup</h2>
      <p className="adm-sub">
        Search, fiscal notes and uploads work with no key at all. This section
        only affects AI Mode.
      </p>

      <fieldset className="adm-field">
        <legend>Where answers come from</legend>
        <label className="adm-radio">
          <input
            type="radio"
            name="provider"
            checked={!isCustom}
            onChange={() => onProviderChange("openrouter")}
          />
          <span>
            <strong>OpenRouter</strong> — one account, many model vendors, one
            bill. This is the supported setup.
          </span>
        </label>
        <label className="adm-radio">
          <input
            type="radio"
            name="provider"
            checked={isCustom}
            onChange={() => onProviderChange("custom")}
          />
          <span>
            <strong>Custom endpoint</strong> — point AI Mode at another
            OpenAI-compatible server.
          </span>
        </label>
      </fieldset>

      {isCustom ? (
        <div className="adm-caveats" data-testid="admin-custom-caveats" role="note">
          <p>
            <strong>Before you use a custom endpoint, know what changes:</strong>
          </p>
          <ul>
            {CUSTOM_CAVEATS.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <button type="button" className="adm-link" onClick={() => onProviderChange("openrouter")}>
            Go back to OpenRouter
          </button>
        </div>
      ) : null}

      {isCustom ? (
        <label className="adm-field">
          <span>Endpoint address</span>
          <input
            type="url"
            value={settings.provider.base_url}
            onChange={(e) => onBaseUrlChange(e.target.value)}
            placeholder="https://my-server.example/v1"
          />
        </label>
      ) : null}

      <div className="adm-field">
        <label htmlFor="adm-key">
          API key
          {settings.provider.api_key_set ? (
            <span className="adm-keyhint" data-testid="admin-key-hint">
              {" "}
              a key ending {settings.provider.api_key_hint} is saved
            </span>
          ) : (
            <span className="adm-keyhint"> no key saved — AI Mode is off</span>
          )}
        </label>
        {editingKey ? (
          <>
            <input
              id="adm-key"
              type="password"
              value={apiKey}
              autoComplete="off"
              onChange={(e) => onApiKeyChange(e.target.value)}
              placeholder="sk-or-v1-…"
            />
            <button type="button" className="adm-link" onClick={() => onApiKeyChange(null)}>
              Cancel — keep the saved key
            </button>
          </>
        ) : (
          <button
            type="button"
            className="adm-btn adm-btn-quiet"
            onClick={() => onApiKeyChange("")}
          >
            {settings.provider.api_key_set ? "Replace the key" : "Add a key"}
          </button>
        )}
      </div>

      <h3>Which model each answer mode uses</h3>
      {models?.note ? (
        <p className="adm-warn" data-testid="admin-models-note">
          {models.note}
        </p>
      ) : null}

      {Object.entries(settings.tiers).map(([tier, cfg]) => {
        const copy = tierCopy?.[tier];
        const recommended = (models?.recommended ?? []).filter(
          (m) => m.tier_hint === tier,
        );
        const configuredMissing =
          cfg.model !== "" &&
          !recommended.some((m) => m.id === cfg.model) &&
          !(models?.catalog ?? []).some((m) => m.id === cfg.model);
        return (
          <div className="adm-tier" key={tier} data-testid={`admin-tier-${tier}`}>
            <label htmlFor={`adm-model-${tier}`}>
              <strong>{copy?.label ?? tier}</strong>
            </label>
            {/* The spec's own sentence, straight from /api/ai/status. Retyping
                it here would let the admin page and the composer's tier toggle
                describe the same mode differently. */}
            {copy ? <p className="adm-sub">{copy.description}</p> : null}
            {isCustom ? (
              <input
                id={`adm-model-${tier}`}
                type="text"
                value={cfg.model}
                onChange={(e) => onTierModelChange(tier, e.target.value)}
                placeholder="vendor/model-name"
              />
            ) : (
              <select
                id={`adm-model-${tier}`}
                value={cfg.model}
                onChange={(e) => onTierModelChange(tier, e.target.value)}
              >
                <option value="">— not set —</option>
                {configuredMissing ? (
                  <option value={cfg.model} disabled>
                    {cfg.model} — no longer offered by OpenRouter
                  </option>
                ) : null}
                {recommended.map((card) => (
                  <ModelOption card={card} key={card.id} />
                ))}
              </select>
            )}
            {!isCustom && recommended.find((m) => m.id === cfg.model)?.blurb ? (
              <p className="adm-blurb">
                {recommended.find((m) => m.id === cfg.model)?.blurb}
              </p>
            ) : null}
          </div>
        );
      })}

      {isCustom ? null : (
        <p className="adm-note">
          Prices are checked with OpenRouter each time this page opens
          {models?.source === "cache" ? " (showing recently cached prices)" : ""}.{" "}
          <button type="button" className="adm-link" onClick={onRefreshModels}>
            Check for new models now
          </button>
        </p>
      )}
    </section>
  );
}
