'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useApp } from '../../context/AppContext';
import { ROUTES, docsPath } from '../../lib/routes';
import { ApiKey } from '../../types';
import { CreatedApiKey } from '../../lib/api';
import { ThinkingLevelSelect } from '../ThinkingLevelSelect';
import { SDK_LEVEL, thinkingOption } from '../../lib/thinkingLevels';
import {
  Key,
  Plus,
  Copy,
  Check,
  Trash2,
  MoreVertical,
  BookOpen,
  Settings2,
  Info,
  X,
  AlertTriangle,
  Loader2,
  Brain
} from 'lucide-react';

export const ApiKeysPage: React.FC = () => {
  const { apiKeys, isApiKeysLoading, createApiKey, updateApiKeyThinkingLevel, deleteApiKey, isLoggedIn } = useApp();
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newKeyName, setNewKeyName] = useState('');
  const [newKeyLevel, setNewKeyLevel] = useState<string>(SDK_LEVEL);
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // One-time secret modal state
  const [justCreatedKey, setJustCreatedKey] = useState<CreatedApiKey | null>(null);
  const [copiedSecret, setCopiedSecret] = useState(false);

  const [copiedKeyId, setCopiedKeyId] = useState<string | null>(null);
  const [activeMenuKeyId, setActiveMenuKeyId] = useState<string | null>(null);
  const [selectedKeyForDetails, setSelectedKeyForDetails] = useState<ApiKey | null>(null);

  // Thinking-level dropdown in the table: which key is saving, which just saved,
  // and the last error (shown above the table so it is not missed).
  const [savingLevelKeyId, setSavingLevelKeyId] = useState<string | null>(null);
  const [savedLevelKeyId, setSavedLevelKeyId] = useState<string | null>(null);
  const [levelError, setLevelError] = useState<string | null>(null);

  const handleLevelChange = async (key: ApiKey, level: string) => {
    if (level === key.thinkingLevel || savingLevelKeyId) return;
    setLevelError(null);
    setSavedLevelKeyId(null);
    setSavingLevelKeyId(key.id);
    try {
      await updateApiKeyThinkingLevel(key.id, level);
      setSavedLevelKeyId(key.id);
      setTimeout(() => setSavedLevelKeyId((cur) => (cur === key.id ? null : cur)), 2000);
    } catch (err: any) {
      setLevelError(err?.message || 'Could not change the thinking level. Nothing was changed.');
    } finally {
      setSavingLevelKeyId(null);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newKeyName.trim() || isCreating) return;
    setIsCreating(true);
    setCreateError(null);
    try {
      const created = await createApiKey(newKeyName.trim(), newKeyLevel);
      setNewKeyName('');
      setNewKeyLevel(SDK_LEVEL);
      setShowCreateModal(false);
      setJustCreatedKey(created);
    } catch (err: any) {
      setCreateError(err.message || 'Failed to create API key');
    } finally {
      setIsCreating(false);
    }
  };

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKeyId(id);
    setTimeout(() => setCopiedKeyId(null), 2000);
  };

  const copySecretToClipboard = (secret: string) => {
    navigator.clipboard.writeText(secret);
    setCopiedSecret(true);
    setTimeout(() => setCopiedSecret(false), 2500);
  };

  return (
    <div className="max-w-[1160px] mx-auto px-[clamp(20px,5vw,48px)] py-[clamp(40px,7vh,64px)] space-y-8">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-5">
        <div>
          <span className="page-eyebrow mb-3">Authentication</span>
          <h1 className="page-title mt-3 mb-2">API Keys</h1>
          <p className="page-lead">
            Keys you generate here authenticate every call to your CIS (Composite Intelligence System).
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Link href={docsPath('authentication')} className="btn-outline-pill !h-[46px] !px-4 !text-[0.8125rem]">
            <BookOpen className="h-4 w-4" />
            <span>Documentation</span>
          </Link>
          <button
            id="open-create-key-modal-btn"
            onClick={() => {
              setCreateError(null);
              setNewKeyLevel(SDK_LEVEL);
              setShowCreateModal(true);
            }}
            className="btn-pill btn-pill-blue !h-[46px] !px-5 !text-[0.8125rem]"
          >
            <Plus className="h-4 w-4" />
            <span>New Key</span>
          </button>
        </div>
      </div>

      {/* What the Thinking column is for. Always visible, not tucked in a tooltip. */}
      <div className="flex items-start gap-3 rounded-2xl border border-accent-blue-border bg-accent-blue-soft p-3.5 text-xs text-ink-2">
        <Brain className="h-4 w-4 text-accent-blue shrink-0 mt-0.5" />
        <p>
          <span className="font-medium text-ink">Thinking level, per key.</span> Leave a key on <strong>SDK</strong> and your
          code decides. Tools that cannot set it themselves, like Cursor, can use a key set to a level here: Low, High or
          Max for Kael Beta, or z-low or z-high for Kael Pro Beta. A level applies to its own model only, so calls to the
          other model still use what your request sets. The change applies from that key&apos;s next request.
        </p>
      </div>

      {levelError && (
        <div className="rounded-xl border border-danger-border bg-danger-soft p-3 text-xs text-danger" role="alert">
          {levelError}
        </div>
      )}

      {/* Keys table */}
      <div className="table-card">
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Key</th>
                <th>Created</th>
                <th>Thinking level</th>
                <th className="text-right" style={{ textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {isApiKeysLoading ? (
                <tr>
                  <td colSpan={5} className="text-center text-ink-3">
                    <div className="flex items-center justify-center gap-2">
                      <Loader2 className="h-4 w-4 animate-spin text-accent-blue" />
                      <span>Loading API keys...</span>
                    </div>
                  </td>
                </tr>
              ) : apiKeys.length === 0 ? (
                <tr>
                  <td colSpan={5} className="text-center text-ink-3">
                    <div className="max-w-xs mx-auto space-y-2 py-4">
                      <p className="font-medium text-ink-2">No API keys yet</p>
                      <p className="text-xs text-ink-3">
                        {isLoggedIn
                          ? 'Create a key above to authenticate API calls and SDK requests.'
                          : 'Sign in to generate and manage your API keys.'}
                      </p>
                    </div>
                  </td>
                </tr>
              ) : (
                apiKeys.map((key) => {
                  return (
                    <tr key={key.id} className="hover:bg-surface transition-colors">
                      <td className="font-medium text-ink">{key.name}</td>

                      <td>
                        <span className="mono-pill">
                          {key.prefix}••••••••
                          <button
                            onClick={() => copyToClipboard(key.prefix, key.id)}
                            className="text-ink-3 hover:text-ink cursor-pointer transition-colors"
                            title="Copy prefix"
                          >
                            {copiedKeyId === key.id ? (
                              <Check className="h-3.5 w-3.5 text-accent-blue" />
                            ) : (
                              <Copy className="h-3.5 w-3.5" />
                            )}
                          </button>
                        </span>
                      </td>

                      <td className="font-mono text-xs whitespace-nowrap">{key.createdAt}</td>
                      <td className="min-w-[190px]">
                        <div className="flex items-center gap-2">
                          <div className="w-[150px]">
                            <ThinkingLevelSelect
                              compact
                              id={`thinking-level-${key.id}`}
                              ariaLabel={`Thinking level for ${key.name}`}
                              value={key.thinkingLevel}
                              disabled={!key.active || savingLevelKeyId === key.id}
                              onChange={(level) => handleLevelChange(key, level)}
                            />
                          </div>
                          <span className="w-4 shrink-0" aria-live="polite">
                            {savingLevelKeyId === key.id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin text-accent-blue" />
                            ) : savedLevelKeyId === key.id ? (
                              <Check className="h-3.5 w-3.5 text-success" />
                            ) : null}
                          </span>
                        </div>
                        <p className="mt-1 text-[11px] leading-snug text-ink-3 max-w-[190px]">
                          {key.thinkingLevel === SDK_LEVEL
                            ? 'Your request decides'
                            : `Pinned for every ${thinkingOption(key.thinkingLevel).modelName ?? 'Kael'} request`}
                        </p>
                      </td>

                      <td className="text-right relative">
                        <div className="inline-block text-left">
                          <button
                            onClick={() => setActiveMenuKeyId(activeMenuKeyId === key.id ? null : key.id)}
                            className="rounded-full p-1.5 text-ink-3 hover:bg-line-soft hover:text-ink transition-colors cursor-pointer"
                            title="Actions"
                          >
                            <MoreVertical className="h-4 w-4" />
                          </button>

                          {activeMenuKeyId === key.id && (
                            <div
                              className="absolute right-4 mt-1 w-48 rounded-2xl border border-line bg-white p-1.5 shadow-[0_18px_40px_-16px_rgba(20,22,24,0.25)] z-30 space-y-0.5 text-left font-sans"
                              onMouseLeave={() => setActiveMenuKeyId(null)}
                            >
                              <button
                                onClick={() => {
                                  setSelectedKeyForDetails(key);
                                  setActiveMenuKeyId(null);
                                }}
                                className="w-full flex items-center gap-2 rounded-xl px-2.5 py-2 text-xs text-ink-2 hover:bg-surface transition-colors cursor-pointer"
                              >
                                <Info className="h-3.5 w-3.5 text-ink-3" />
                                <span>View Details</span>
                              </button>
                              <div className="my-1 border-t border-line-soft" />
                              <button
                                onClick={async () => {
                                  try {
                                    await deleteApiKey(key.id);
                                  } catch (e) {
                                    // Error logged in context
                                  }
                                  setActiveMenuKeyId(null);
                                }}
                                className="w-full flex items-center gap-2 rounded-xl px-2.5 py-2 text-xs text-danger hover:bg-danger-soft transition-colors cursor-pointer font-medium"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                                <span>Delete Key</span>
                              </button>
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* One-Time Key Secret Display Modal */}
      {justCreatedKey && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg rounded-[28px] border border-line bg-white p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-line-soft pb-3">
              <h3 className="text-base font-medium text-ink tracking-[-0.01em] flex items-center gap-2">
                <Key className="h-5 w-5 text-accent-blue" />
                API Key Created
              </h3>
              <button
                onClick={() => setJustCreatedKey(null)}
                className="text-ink-3 hover:text-ink p-1 rounded-xl cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="flex items-start gap-3 rounded-2xl border border-warning-border bg-warning-soft p-3.5 text-xs text-warning">
              <AlertTriangle className="h-5 w-5 text-warning shrink-0 mt-0.5" />
              <div>
                <p className="font-medium">Save your secret key now</p>
                <p className="mt-0.5 text-warning">
                  Please save this key somewhere secure. For security reasons, you will not be able to view it again.
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3 rounded-2xl border border-accent-blue-border bg-accent-blue-soft p-3.5 text-xs text-ink-2">
              <Brain className="h-4 w-4 text-accent-blue shrink-0 mt-0.5" />
              <p>
                Thinking level: <strong className="text-ink">{thinkingOption(justCreatedKey.thinking_level).fullLabel}</strong>.
                You can change it anytime from the <strong>Thinking level</strong> dropdown in your keys table.
              </p>
            </div>

            <div className="space-y-2">
              <label className="block text-xs font-medium text-ink-2">
                Secret Key ({justCreatedKey.name})
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  readOnly
                  value={justCreatedKey.secret}
                  className="w-full rounded-xl border border-line bg-surface px-3 py-2.5 font-mono text-xs text-ink focus:outline-none select-all"
                />
                <button
                  type="button"
                  onClick={() => copySecretToClipboard(justCreatedKey.secret)}
                  className="btn-pill btn-pill-blue !h-11 !px-4 !text-xs shrink-0"
                >
                  {copiedSecret ? (
                    <>
                      <Check className="h-4 w-4" />
                      <span>Copied!</span>
                    </>
                  ) : (
                    <>
                      <Copy className="h-4 w-4" />
                      <span>Copy</span>
                    </>
                  )}
                </button>
              </div>
            </div>

            <div className="flex justify-end pt-3 border-t border-line-soft">
              <button
                type="button"
                onClick={() => setJustCreatedKey(null)}
                className="btn-pill btn-pill-dark !h-10 !px-5 !text-xs"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Key Details Modal */}
      {selectedKeyForDetails && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-[28px] border border-line bg-white p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-line-soft pb-3">
              <h3 className="text-base font-medium text-ink tracking-[-0.01em] flex items-center gap-2">
                <Settings2 className="h-4 w-4 text-accent-blue" />
                Key Details
              </h3>
              <button
                onClick={() => setSelectedKeyForDetails(null)}
                className="text-ink-3 hover:text-ink p-1 rounded-xl cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div className="rounded-2xl bg-surface p-3.5 border border-line space-y-2.5">
                <div className="flex justify-between items-center">
                  <span className="text-ink-3 font-medium">Name:</span>
                  <span className="font-medium text-ink">{selectedKeyForDetails.name}</span>
                </div>
                <div className="flex justify-between items-center font-mono">
                  <span className="text-ink-3 font-sans">Key Prefix:</span>
                  <span className="text-ink text-[11px] bg-white px-2 py-0.5 rounded-lg border border-line">
                    {selectedKeyForDetails.prefix}••••••••
                  </span>
                </div>
                <div className="flex justify-between items-center font-mono text-[11px]">
                  <span className="text-ink-3 font-sans">Created:</span>
                  <span className="text-ink-2">{selectedKeyForDetails.createdAt}</span>
                </div>
                <div className="flex justify-between items-center font-mono text-[11px]">
                  <span className="text-ink-3 font-sans">Last Used:</span>
                  <span className="text-ink-2">{selectedKeyForDetails.lastUsedAt}</span>
                </div>
                <div className="flex justify-between items-center text-[11px]">
                  <span className="text-ink-3">Thinking level:</span>
                  <span className="font-medium text-ink">{thinkingOption(selectedKeyForDetails.thinkingLevel).fullLabel}</span>
                </div>
              </div>
            </div>

            <div className="flex justify-between items-center pt-3 border-t border-line-soft">
              <button
                type="button"
                onClick={async () => {
                  try {
                    await deleteApiKey(selectedKeyForDetails.id);
                  } catch (e) {
                    // Error logged in context
                  }
                  setSelectedKeyForDetails(null);
                }}
                className="rounded-xl border border-danger-border bg-danger-soft px-3.5 py-2 text-xs font-medium text-danger hover:bg-[#FDE7E5] cursor-pointer transition-colors"
              >
                Delete Key
              </button>
              <button
                type="button"
                onClick={() => setSelectedKeyForDetails(null)}
                className="btn-pill btn-pill-dark !h-10 !px-5 !text-xs"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-[28px] border border-line bg-white p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-line-soft pb-3">
              <h3 className="text-base font-medium text-ink tracking-[-0.01em] flex items-center gap-2">
                <Key className="h-4 w-4 text-accent-blue" />
                Generate New Key
              </h3>
              <button
                onClick={() => setShowCreateModal(false)}
                className="text-ink-3 hover:text-ink text-lg leading-none cursor-pointer"
              >
                &times;
              </button>
            </div>

            {createError && (
              <div className="rounded-xl border border-danger-border bg-danger-soft p-3 text-xs text-danger">
                {createError}
              </div>
            )}

            <form onSubmit={handleCreate} className="space-y-4 text-xs">
              <div>
                <label className="block font-medium text-ink-2 mb-1.5">
                  Key Name
                </label>
                <input
                  type="text"
                  required
                  value={newKeyName}
                  onChange={(e) => setNewKeyName(e.target.value)}
                  placeholder="e.g. Production, CI/CD, or Development"
                  className="w-full rounded-xl border border-line bg-surface px-3 py-2.5 text-xs text-ink placeholder:text-ink-3 focus:border-accent-blue focus:bg-white focus:outline-none"
                />
              </div>

              <div>
                <label htmlFor="new-key-thinking-level" className="block font-medium text-ink-2 mb-1.5">
                  Thinking level
                </label>
                <ThinkingLevelSelect
                  id="new-key-thinking-level"
                  value={newKeyLevel}
                  disabled={isCreating}
                  onChange={setNewKeyLevel}
                />
                <p className="mt-1.5 text-[11px] leading-snug text-ink-3">{thinkingOption(newKeyLevel).hint}</p>
                <p className="mt-1 text-[11px] leading-snug text-ink-3">
                  Pick SDK if your code sets it per request. Tools like Cursor can&apos;t, so choose a level for them. A
                  level applies to its own model only. You can change this anytime from the{' '}
                  <span className="font-medium text-ink-2">Thinking level</span> dropdown in the keys table.
                </p>
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-line-soft">
                <button
                  type="button"
                  disabled={isCreating}
                  onClick={() => setShowCreateModal(false)}
                  className="btn-outline-pill !h-10 !px-4 !text-xs disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isCreating || !newKeyName.trim()}
                  className="btn-pill btn-pill-blue !h-10 !px-4 !text-xs disabled:opacity-50"
                >
                  {isCreating && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  <span>{isCreating ? 'Creating...' : 'Create Key'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
