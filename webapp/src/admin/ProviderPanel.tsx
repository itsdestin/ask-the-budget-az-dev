import * as api from "../api";
import { Card, CollapsibleCard } from "./Card";
import { ModelPicker } from "./ModelPicker";
import { Toggle } from "./Toggle";

// AI Mode, as a chain of switches that each reveal the next decision
// (2026-07-31, Destin):
//
//     AI Mode [off] ──▶ nothing else on screen
//               [on] ──▶ Key
//        key added   ──▶ Standard Search [off/on] ──▶ its model
//                        Deep Research   [off/on] ──▶ its model
//                        Spending limits, Which AI service
//
// Everything below a switch is genuinely absent until it is relevant, rather
// than present-but-disabled. A greyed-out model picker above a key field
// invites an admin to try the picker first and conclude the page is broken.
//
// The switches are real settings, not view state: turning Deep Research off
// keeps the model it was using, so turning it back on is not a fresh
// decision. That is why `TierConfig.enabled` exists at all.

const CUSTOM_CAVEATS = [
  "You have to tell the app what your service charges, so it can still show spending and enforce limits.",
  "There is no model list and no live prices — you type the model name your service expects.",
  "The model must support tool calling. AI Mode searches before it answers, so a model without it fails every question rather than answering worse.",
  "If answers stop working, the app can only show you what your service replied.",
];

export function ProviderPanel({
  settings,
  models,
  tierCopy,
  apiKey,
  onApiKeyChange,
  onAiEnabledChange,
  onTierEnabledChange,
  onProviderChange,
  onBaseUrlChange,
  onPriceChange,
  onTierModelChange,
  onRefreshModels,
  limitsActive,
  limitsInactiveReason,
  onDefaultChange,
}: {
  settings: api.AdminSettings;
  models: api.ModelCatalog | null;
  tierCopy: Record<string, api.AiTierInfo> | null;
  apiKey: string | null;
  onApiKeyChange: (value: string | null) => void;
  onAiEnabledChange: (next: boolean) => void;
  onTierEnabledChange: (tier: string, next: boolean) => void;
  onProviderChange: (provider: "openrouter" | "custom") => void;
  onBaseUrlChange: (value: string) => void;
  onPriceChange: (field: "prompt_usd_per_m" | "completion_usd_per_m", value: number | null) => void;
  onTierModelChange: (tier: string, model: string) => void;
  onRefreshModels: () => void;
  limitsActive: boolean;
  limitsInactiveReason: string | null;
  onDefaultChange: (value: number | null) => void;
}) {
  const isCustom = settings.provider.provider === "custom";
  const editingKey = apiKey !== null;
  // A key the admin has typed but not saved yet still counts — otherwise the
  // answer-mode cards would not appear until after a save, and the flow would
  // stall exactly where it should be moving forward.
  const hasKey = settings.provider.api_key_set || Boolean(apiKey);

  return (
    <section className="card adm-panel" aria-labelledby="adm-ai-h" data-testid="admin-provider">
      <div className="adm-panel-head">
        <h2 id="adm-ai-h">AI Mode</h2>
        <Toggle
          checked={settings.ai_enabled}
          onChange={onAiEnabledChange}
          label="AI Mode"
          testId="admin-ai-toggle"
        />
      </div>
      <p className="adm-sub">
        Answers questions using the documents, at a cost per question.
        Searching, fiscal notes and uploads never need any of this.
      </p>

      {!settings.ai_enabled ? null : (
        <>
          <Card
            title="Key"
            hint={
              settings.provider.api_key_set
                ? `saved, ending ${settings.provider.api_key_hint}`
                : "none yet"
            }
            testId="admin-key-card"
            action={
              editingKey ? (
                <button type="button" className="adm-btn adm-btn-quiet adm-btn-sm" onClick={() => onApiKeyChange(null)}>
                  Cancel
                </button>
              ) : (
                <button
                  type="button"
                  className="adm-btn adm-btn-quiet"
                  onClick={() => onApiKeyChange("")}
                >
                  {settings.provider.api_key_set ? "Replace" : "Add a key"}
                </button>
              )
            }
          >
            {editingKey ? (
              <input
                id="adm-key"
                type="password"
                value={apiKey}
                autoComplete="off"
                onChange={(e) => onApiKeyChange(e.target.value)}
                placeholder="sk-or-v1-…"
                aria-label="API key"
              />
            ) : settings.provider.api_key_set ? null : (
              <p className="adm-hint">
                {isCustom
                  ? "The key your own AI service expects."
                  : "Create one on your OpenRouter account, then paste it here. Set a hard monthly cap there too — that is the only limit that stops spending outright."}
              </p>
            )}
          </Card>

          {!hasKey ? (
            <p className="adm-hint" data-testid="admin-needs-key">
              Add a key to choose which models answer questions.
            </p>
          ) : (
            <>
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
                const chosen = recommended.find((m) => m.id === cfg.model);
                return (
                  <Card
                    key={tier}
                    title={copy?.label ?? tier}
                    hint={cfg.enabled ? (chosen?.name ?? cfg.model ?? "") : undefined}
                    testId={`admin-tier-${tier}`}
                    action={
                      <Toggle
                        checked={cfg.enabled}
                        onChange={(next) => onTierEnabledChange(tier, next)}
                        label={copy?.label ?? tier}
                        testId={`admin-tier-toggle-${tier}`}
                      />
                    }
                  >
                    {/* The spec's own sentence, straight from /api/ai/status.
                        Retyping it here would let this page and the composer's
                        mode toggle describe the same thing differently. */}
                    {copy ? <p className="adm-sub">{copy.description}</p> : null}

                    {!cfg.enabled ? null : isCustom ? (
                      <input
                        id={`adm-model-${tier}`}
                        type="text"
                        value={cfg.model}
                        onChange={(e) => onTierModelChange(tier, e.target.value)}
                        placeholder="the model name your service expects"
                        aria-label={`Model for ${copy?.label ?? tier}`}
                      />
                    ) : (
                      <ModelPicker
                        tier={tier}
                        label={copy?.label ?? tier}
                        selected={cfg.model}
                        options={recommended}
                        onChange={(model) => onTierModelChange(tier, model)}
                      />
                    )}
                  </Card>
                );
              })}

              {isCustom ? null : (
                <p className="adm-hint">
                  <button type="button" className="adm-btn adm-btn-quiet adm-btn-sm" onClick={onRefreshModels}>
                    Check for new models
                  </button>
                </p>
              )}

              <CollapsibleCard
                title="Spending limits"
                hint={
                  settings.default_monthly_limit_usd === null
                    ? "nobody is capped"
                    : `$${settings.default_monthly_limit_usd} a month each`
                }
                testId="admin-limits"
              >
                <p className="adm-sub">
                  <strong>Searching is never affected.</strong> Someone at their
                  limit can still search, browse fiscal notes and upload.
                </p>

                {!limitsActive && limitsInactiveReason ? (
                  <p className="adm-warn" data-testid="admin-limits-warning">
                    {limitsInactiveReason === "custom endpoint"
                      ? "These aren't being enforced: your AI service has no prices set, so the app can't tell when someone reaches a limit."
                      : "Nothing is capped until you set a monthly limit here. The hard cap on your OpenRouter account is what actually stops spending."}
                  </p>
                ) : null}

                <label className="adm-field">
                  <span className="adm-label">Each person, per month</span>
                  <input
                    type="number"
                    min={0}
                    step="1"
                    value={settings.default_monthly_limit_usd ?? ""}
                    placeholder="no limit"
                    onChange={(e) =>
                      onDefaultChange(e.target.value === "" ? null : Number(e.target.value))
                    }
                  />
                  <span className="adm-hint">
                    Blank means no limit. 0 blocks everyone. Set one person's own
                    limit, or no limit, under <strong>People</strong>.
                  </span>
                </label>
              </CollapsibleCard>

              <CollapsibleCard
                title="Which AI service"
                hint={isCustom ? settings.provider.base_url : "OpenRouter"}
                defaultOpen={isCustom}
                testId="admin-service"
              >
                <fieldset className="adm-field">
                  <legend className="adm-vh">Which AI service</legend>
                  <label className="adm-radio">
                    <input
                      type="radio"
                      name="provider"
                      checked={!isCustom}
                      onChange={() => onProviderChange("openrouter")}
                    />
                    <span>
                      <strong>OpenRouter</strong> — one account, many model
                      vendors, one bill. This is the supported setup.
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
                      <strong>Something else</strong> — another service that
                      speaks the same protocol.
                    </span>
                  </label>
                </fieldset>

                {isCustom ? (
                  <>
                    <div className="adm-caveats" data-testid="admin-custom-caveats" role="note">
                      <p>
                        <strong>What changes if you do this:</strong>
                      </p>
                      <ul>
                        {CUSTOM_CAVEATS.map((line) => (
                          <li key={line}>{line}</li>
                        ))}
                      </ul>
                      <button
                        type="button"
                        className="adm-btn adm-btn-quiet adm-btn-sm"
                        onClick={() => onProviderChange("openrouter")}
                      >
                        Go back to OpenRouter
                      </button>
                    </div>

                    <label className="adm-field">
                      <span className="adm-label">Address</span>
                      <input
                        type="url"
                        value={settings.provider.base_url}
                        onChange={(e) => onBaseUrlChange(e.target.value)}
                        placeholder="https://my-server.example/v1"
                      />
                    </label>

                    {/* Required, not optional. Without both figures every
                        request lands with no cost, which makes spending
                        invisible AND silently switches limits off. The server
                        refuses the save. */}
                    <div className="adm-field" data-testid="admin-custom-prices">
                      <span className="adm-label">What it charges</span>
                      <p className="adm-hint">
                        Per million tokens, the way AI services quote prices. A
                        token is roughly three-quarters of a word. Copy both
                        figures from your service's pricing page.
                      </p>
                      <div className="adm-inline">
                        <label>
                          <span className="adm-hint">Input</span>
                          <input
                            type="number"
                            min={0}
                            step="0.01"
                            aria-label="Price per million input tokens, in dollars"
                            value={settings.provider.prompt_usd_per_m ?? ""}
                            placeholder="0.00"
                            onChange={(e) =>
                              onPriceChange(
                                "prompt_usd_per_m",
                                e.target.value === "" ? null : Number(e.target.value),
                              )
                            }
                          />
                        </label>
                        <label>
                          <span className="adm-hint">Output</span>
                          <input
                            type="number"
                            min={0}
                            step="0.01"
                            aria-label="Price per million output tokens, in dollars"
                            value={settings.provider.completion_usd_per_m ?? ""}
                            placeholder="0.00"
                            onChange={(e) =>
                              onPriceChange(
                                "completion_usd_per_m",
                                e.target.value === "" ? null : Number(e.target.value),
                              )
                            }
                          />
                        </label>
                      </div>
                    </div>
                  </>
                ) : null}
              </CollapsibleCard>
            </>
          )}
        </>
      )}
    </section>
  );
}
