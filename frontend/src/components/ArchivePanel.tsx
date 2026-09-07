import { Fragment, useState, useEffect, useCallback } from 'react';
import { EuringAPI } from '../services/api';
import { authService } from '../services/auth';
import './ArchivePanel.css';

interface FacetValue {
  value: string;
  count: number;
}

type Visibility = 'public' | 'private' | 'shared';

// Priorita' #6 della scaletta (02-04/09/2026, piramide ruoli/livelli): le
// righe non piu' a Livello 3 non portano canonical_string (mai la stringa
// grezza sotto Livello 3, vincolo del documento di design) ma
// masked_fields -- solo i campi dei domini permessi dal livello calcolato.
interface CanonicalRow {
  id: number;
  canonical_string: string | null;
  level: 1 | 2 | 3;
  masked_fields: Record<string, string> | null;
  field_count: number;
  first_seen: string;
  last_seen: string;
  occurrence_count: number;
  visibility: Visibility;
  alias_id: number | null;
}

interface SearchResponse {
  success: boolean;
  total: number;
  page: number;
  page_size: number;
  results: CanonicalRow[];
  facets: Record<string, FacetValue[]>;
}

interface LifeHistoryFullEvent {
  kind: 'full';
  id: number;
  canonical_string: string;
  field_count: number;
  visibility: Visibility;
  is_own: boolean;
  event_date: string | null;
  first_seen: string | null;
  last_seen: string | null;
  occurrence_count: number;
}

// Sostituisce il precedente 'hidden' a 3 campi fissi con il mascheramento
// a Livello 1/2 completo (priorita' #6, 02-04/09/2026) -- year/country/
// species_code restano come carve-out anti-frode deciso con Davide il
// 03/08/2026 (vedi database_service.get_alias_life_history), in aggiunta a
// masked_fields, non al posto suo.
interface LifeHistoryMaskedEvent {
  kind: 'masked';
  level: 1 | 2;
  masked_fields: Record<string, string>;
  year: string | null;
  country: string | null;
  species_code: string | null;
}

type LifeHistoryEvent = LifeHistoryFullEvent | LifeHistoryMaskedEvent;

interface AliasSummary {
  success: boolean;
  alias_id: number;
  visible_count: number;
  total_count: number;
  hidden_count: number;
  life_history: LifeHistoryEvent[];
}

// Storico immutabile di ogni scelta di condivisione mai fatta tra i due
// proprietari (migrazione 006, 07/09/2026) -- risponde al rischio "nessuna
// prova in caso di disputa / messaggio modificato senza preavviso"
// sollevato da Davide dopo aver visto che alias_sharing_intent e' un
// semplice UPSERT senza traccia. Ordine cronologico crescente (dal server).
interface SharingHistoryEntry {
  from_username: string;
  state: 'offered' | 'declined';
  message: string | null;
  decided_at: string;
}

interface SharingOther {
  username: string;
  my_state: 'offered' | 'declined' | null;
  my_message: string | null;
  their_state: 'offered' | 'declined' | null;
  their_message: string | null;
  mutually_shared: boolean;
  history: SharingHistoryEntry[];
}

interface SharingStatus {
  success: boolean;
  is_public: boolean;
  others: SharingOther[];
}

const VISIBILITY_LABELS: Record<Visibility, string> = {
  public: 'Pubblico',
  private: 'Privato',
  shared: 'Condiviso',
};

// Etichetta per ogni voce di cronologia condivisione (migrazione 006).
const SHARING_STATE_LABELS: Record<'offered' | 'declined', string> = {
  offered: 'Condiviso',
  declined: 'Non condiviso',
};

const formatHistoryDate = (iso: string): string => {
  try {
    return new Date(iso).toLocaleString('it-IT', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return iso;
  }
};

// Priorita' #6 (02-04/09/2026): etichetta breve per il livello di dettaglio
// mostrato al posto della stringa grezza sotto Livello 3.
const LEVEL_LABELS: Record<1 | 2 | 3, string> = {
  1: 'Livello 1 — specie e metodologia',
  2: 'Livello 2 — + demografia, anello mascherato',
  3: 'Livello 3 — completo',
};

// Rende leggibili i masked_fields (dizionario campo EURING -> valore) senza
// dover conoscere in anticipo quali campi arriveranno -- lo stesso oggetto
// puo' contenere domini diversi a seconda del livello.
const formatMaskedFields = (fields: Record<string, string> | null | undefined): string => {
  if (!fields) return '';
  const entries = Object.entries(fields).filter(([key]) => key !== 'masked_alias_id');
  if (entries.length === 0) return '';
  return entries.map(([key, value]) => `${key}: ${value}`).join(' · ');
};

const FACET_LABELS: Record<string, string> = {
  'ringing scheme': 'Scheme di inanellamento',
  'species concluded': 'Specie conclusa',
  'sex concluded': 'Sesso concluso',
  'age concluded': "Età conclusa",
  'condition': 'Condizione',
  'circumstances': 'Circostanze',
};

const PAGE_SIZE = 20;

const ArchivePanel = () => {
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [page, setPage] = useState(1);
  const [data, setData] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const [expandedRowId, setExpandedRowId] = useState<number | null>(null);
  const [aliasSummaries, setAliasSummaries] = useState<Record<number, AliasSummary>>({});
  const [summaryLoading, setSummaryLoading] = useState<Record<number, boolean>>({});
  const [sharingStatuses, setSharingStatuses] = useState<Record<number, SharingStatus>>({});
  const [sharingMessages, setSharingMessages] = useState<Record<string, string>>({});
  const [sharingBusy, setSharingBusy] = useState<Record<string, boolean>>({});
  const [sharingError, setSharingError] = useState<Record<number, string>>({});
  // Cronologia condivisione (migrazione 006): chiusa di default per non
  // appesantire la vista, apribile per riga+proprietario.
  const [expandedHistory, setExpandedHistory] = useState<Record<string, boolean>>({});

  const isAuthenticated = authService.isAuthenticated();

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await EuringAPI.searchArchive(filters, page, PAGE_SIZE);
      setData(response);
    } catch (err: any) {
      setError(err.message || 'Errore nella ricerca');
    } finally {
      setLoading(false);
    }
  }, [filters, page]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const toggleFilter = (field: string, value: string) => {
    setPage(1);
    setFilters((prev) => {
      const next = { ...prev };
      if (next[field] === value) {
        delete next[field];
      } else {
        next[field] = value;
      }
      return next;
    });
  };

  const clearFilters = () => {
    setPage(1);
    setFilters({});
  };

  const toggleRowDetail = async (row: CanonicalRow) => {
    if (expandedRowId === row.id) {
      setExpandedRowId(null);
      return;
    }
    setExpandedRowId(row.id);

    if (row.alias_id != null && !aliasSummaries[row.id] && !summaryLoading[row.id]) {
      setSummaryLoading((prev) => ({ ...prev, [row.id]: true }));
      try {
        const summary = await EuringAPI.getAliasSummary(row.alias_id);
        setAliasSummaries((prev) => ({ ...prev, [row.id]: summary }));
      } catch {
        // silenzioso in UI: il badge di visibilità resta comunque leggibile
      } finally {
        setSummaryLoading((prev) => ({ ...prev, [row.id]: false }));
      }
    }

    // Stato di condivisione: richiede di possedere gia' un proprio dato su
    // questo alias (verificato server-side, 403 altrimenti) -- per questo
    // il fallimento e' silenzioso, non tutti gli utenti che aprono i
    // dettagli sono proprietari di quell'anello.
    if (isAuthenticated && row.alias_id != null && !sharingStatuses[row.id]) {
      try {
        const status = await EuringAPI.getAliasSharingStatus(row.alias_id);
        setSharingStatuses((prev) => ({ ...prev, [row.id]: status }));
      } catch {
        // non proprietario di questo alias, o errore -- nessuna sezione di gestione mostrata
      }
    }
  };

  const refreshSharingStatus = async (row: CanonicalRow) => {
    if (row.alias_id == null) return;
    try {
      const status = await EuringAPI.getAliasSharingStatus(row.alias_id);
      setSharingStatuses((prev) => ({ ...prev, [row.id]: status }));
    } catch (err: any) {
      setSharingError((prev) => ({ ...prev, [row.id]: err.message || 'Aggiornamento stato fallito' }));
    }
  };

  // Bug trovato con Davide il 09/08/2026: togglePublic/setSharingWith
  // aggiornavano solo sharingStatuses (la sezione "condivisione"), ma la
  // "Storia di vita dell'anello" viene da una chiamata separata
  // (getAliasSummary, fatta una volta sola all'apertura dei dettagli) e
  // restava quindi non aggiornata dopo un cambio di visibilita' -- la
  // checkbox "pubblico" risultava spuntata ma la riga in storia di vita
  // continuava a mostrare "Privato" finche' non si chiudeva e riapriva il
  // dettaglio. Ora rinfreschiamo anche aliasSummaries dopo ogni azione.
  const refreshAliasSummary = async (row: CanonicalRow) => {
    if (row.alias_id == null) return;
    try {
      const summary = await EuringAPI.getAliasSummary(row.alias_id);
      setAliasSummaries((prev) => ({ ...prev, [row.id]: summary }));
    } catch {
      // silenzioso: non deve bloccare l'aggiornamento dello stato di condivisione
    }
  };

  const togglePublic = async (row: CanonicalRow, isPublic: boolean) => {
    if (row.alias_id == null) return;
    const key = `${row.id}-public`;
    setSharingBusy((prev) => ({ ...prev, [key]: true }));
    setSharingError((prev) => ({ ...prev, [row.id]: '' }));
    try {
      await EuringAPI.setAliasPublic(row.alias_id, isPublic);
      await Promise.all([refreshSharingStatus(row), refreshAliasSummary(row)]);
    } catch (err: any) {
      setSharingError((prev) => ({ ...prev, [row.id]: err.message || 'Aggiornamento fallito' }));
    } finally {
      setSharingBusy((prev) => ({ ...prev, [key]: false }));
    }
  };

  const setSharingWith = async (row: CanonicalRow, toUsername: string, state: 'offered' | 'declined') => {
    if (row.alias_id == null) return;
    const msgKey = `${row.id}-${toUsername}`;
    const key = `${row.id}-${toUsername}-${state}`;
    setSharingBusy((prev) => ({ ...prev, [key]: true }));
    setSharingError((prev) => ({ ...prev, [row.id]: '' }));
    try {
      await EuringAPI.setAliasSharing(row.alias_id, toUsername, state, sharingMessages[msgKey] || undefined);
      await Promise.all([refreshSharingStatus(row), refreshAliasSummary(row)]);
    } catch (err: any) {
      setSharingError((prev) => ({ ...prev, [row.id]: err.message || 'Aggiornamento fallito' }));
    } finally {
      setSharingBusy((prev) => ({ ...prev, [key]: false }));
    }
  };

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <div className="archive-panel">
      <div className="archive-header">
        <div>
          <div className="archive-title">Archivio EURING 2020</div>
          <div className="archive-subtitle">Ricerca a faccette sulle stringhe archiviate</div>
        </div>
        <div className="archive-total-badge">
          {data ? `${data.total.toLocaleString('it-IT')} stringhe` : '...'}
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="archive-body">
        <aside className="archive-sidebar">
          {Object.keys(FACET_LABELS).map((field) => {
            const facetValues = data?.facets?.[field] || [];
            if (facetValues.length === 0) return null;
            return (
              <div className="facet-group" key={field}>
                <div className="facet-group-title">{FACET_LABELS[field]}</div>
                {facetValues.map((fv) => (
                  <label className="facet-option" key={fv.value}>
                    <input
                      type="checkbox"
                      checked={filters[field] === fv.value}
                      onChange={() => toggleFilter(field, fv.value)}
                    />
                    <span className="facet-option-label">{fv.value}</span>
                    <span className="facet-option-count">{fv.count}</span>
                  </label>
                ))}
              </div>
            );
          })}
          {Object.keys(filters).length > 0 && (
            <button className="archive-clear-btn" onClick={clearFilters}>
              Rimuovi tutti i filtri
            </button>
          )}
        </aside>

        <main className="archive-results">
          {loading ? (
            <div className="archive-loading">Caricamento...</div>
          ) : (
            <>
              <div className="archive-table-wrapper">
                <table className="archive-table">
                  <thead>
                    <tr>
                      <th>Stringa canonica</th>
                      <th>Campi</th>
                      <th>Prima vista</th>
                      <th>Occorrenze</th>
                      <th>Visibilità</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data?.results || []).map((row) => {
                      const summary = aliasSummaries[row.id];
                      const isExpanded = expandedRowId === row.id;
                      return (
                        <Fragment key={row.id}>
                          <tr>
                            {row.level >= 3 ? (
                              <td className="archive-string-cell" title={row.canonical_string || ''}>
                                {row.canonical_string}
                              </td>
                            ) : (
                              <td className="archive-string-cell archive-string-masked" title={formatMaskedFields(row.masked_fields)}>
                                <span className="level-badge" title={LEVEL_LABELS[row.level]}>
                                  {LEVEL_LABELS[row.level]}
                                </span>
                                <span className="archive-masked-fields">
                                  {formatMaskedFields(row.masked_fields) || 'Nessun campo visibile a questo livello'}
                                </span>
                              </td>
                            )}
                            <td>{row.field_count}</td>
                            <td>{new Date(row.first_seen).toLocaleDateString('it-IT')}</td>
                            <td>{row.occurrence_count}</td>
                            <td>
                              <span className={`visibility-badge visibility-${row.visibility}`}>
                                {VISIBILITY_LABELS[row.visibility] || row.visibility}
                              </span>
                            </td>
                            <td>
                              {row.alias_id != null && (
                                <button
                                  className="archive-detail-btn"
                                  onClick={() => toggleRowDetail(row)}
                                >
                                  {isExpanded ? 'Chiudi' : 'Dettagli anello'}
                                </button>
                              )}
                            </td>
                          </tr>
                          {isExpanded && (
                            <tr key={`${row.id}-detail`} className="archive-detail-row">
                              <td colSpan={6}>
                                {summaryLoading[row.id] && <div>Caricamento riepilogo anello...</div>}
                                {!summaryLoading[row.id] && summary && (
                                  <div className="archive-detail-content">
                                    <div>
                                      Eventi visibili per te: <strong>{summary.visible_count}</strong> su{' '}
                                      <strong>{summary.total_count}</strong> totali per questo anello.
                                    </div>
                                    {summary.life_history && summary.life_history.length > 0 && (
                                      <div className="life-history">
                                        <div className="life-history-title">Storia di vita dell'anello</div>
                                        {summary.life_history.map((ev, idx) =>
                                          ev.kind === 'full' ? (
                                            <div className="life-history-item life-history-full" key={`full-${ev.id}`}>
                                              <span
                                                className="life-history-date"
                                                title={
                                                  ev.event_date
                                                    ? undefined
                                                    : 'Data evento non disponibile: mostrata la data di archiviazione in ECES'
                                                }
                                              >
                                                {ev.event_date
                                                  ? ev.event_date
                                                  : ev.first_seen
                                                  ? `(archiviato ${new Date(ev.first_seen).toLocaleDateString('it-IT')})`
                                                  : '?'}
                                              </span>
                                              <span className={`visibility-badge visibility-${ev.visibility}`}>
                                                {VISIBILITY_LABELS[ev.visibility] || ev.visibility}
                                              </span>
                                              <span className="life-history-string" title={ev.canonical_string}>
                                                {ev.canonical_string}
                                              </span>
                                              {ev.is_own && <span className="life-history-own">(tuo)</span>}
                                            </div>
                                          ) : (
                                            <div className="life-history-item life-history-masked" key={`masked-${idx}`}>
                                              <span className="level-badge" title={LEVEL_LABELS[ev.level]}>
                                                {LEVEL_LABELS[ev.level]}
                                              </span>
                                              <span className="life-history-placeholder">
                                                {ev.year || '????'} · {ev.country || '??'} · specie {ev.species_code || '?'}
                                              </span>
                                              {formatMaskedFields(ev.masked_fields) && (
                                                <span className="archive-masked-fields">
                                                  {formatMaskedFields(ev.masked_fields)}
                                                </span>
                                              )}
                                            </div>
                                          )
                                        )}
                                      </div>
                                    )}
                                    {summary.hidden_count > 0 && !sharingStatuses[row.id] && (
                                      <div className="archive-hidden-note">
                                        {summary.hidden_count} evento/i non condivisi con te.
                                        {!isAuthenticated && (
                                          <span> Accedi per gestire la condivisione dei tuoi dati su questo anello.</span>
                                        )}
                                      </div>
                                    )}
                                    {sharingStatuses[row.id] && (
                                      <div className="sharing-manager">
                                        <div className="sharing-manager-title">
                                          Le tue scelte di condivisione per questo anello
                                        </div>
                                        <label className="sharing-public-toggle">
                                          <input
                                            type="checkbox"
                                            checked={sharingStatuses[row.id].is_public}
                                            disabled={sharingBusy[`${row.id}-public`]}
                                            onChange={(e) => togglePublic(row, e.target.checked)}
                                          />
                                          Rendi pubblico il tuo dato su questo anello
                                        </label>

                                        {sharingStatuses[row.id].others.map((other) => {
                                          const msgKey = `${row.id}-${other.username}`;
                                          const offeredKey = `${row.id}-${other.username}-offered`;
                                          const declinedKey = `${row.id}-${other.username}-declined`;
                                          return (
                                            <div className="sharing-row" key={other.username}>
                                              <div className="sharing-row-header">
                                                <span className="sharing-username">{other.username}</span>
                                                <span className="sharing-their-state">
                                                  {other.their_state === 'offered'
                                                    ? 'ha scelto di condividere con te'
                                                    : other.their_state === 'declined'
                                                    ? 'ha rifiutato di condividere con te'
                                                    : 'non ha ancora deciso'}
                                                </span>
                                                {other.mutually_shared && (
                                                  <span className="sharing-mutual-badge">Condivisione reciproca attiva</span>
                                                )}
                                              </div>
                                              {other.their_message && (
                                                <div className="sharing-received-message">
                                                  Messaggio da {other.username}: "{other.their_message}"
                                                </div>
                                              )}
                                              <textarea
                                                className="sharing-message"
                                                placeholder="Messaggio facoltativo..."
                                                rows={1}
                                                value={sharingMessages[msgKey] || ''}
                                                onChange={(e) =>
                                                  setSharingMessages((prev) => ({ ...prev, [msgKey]: e.target.value }))
                                                }
                                              />
                                              <div className="sharing-actions">
                                                <button
                                                  className={other.my_state === 'offered' ? 'sharing-active' : ''}
                                                  disabled={sharingBusy[offeredKey]}
                                                  onClick={() => setSharingWith(row, other.username, 'offered')}
                                                >
                                                  {other.my_state === 'offered' ? 'Condiviso ✓' : 'Condividi'}
                                                </button>
                                                <button
                                                  className={other.my_state === 'declined' ? 'sharing-active' : ''}
                                                  disabled={sharingBusy[declinedKey]}
                                                  onClick={() => setSharingWith(row, other.username, 'declined')}
                                                >
                                                  {other.my_state === 'declined' ? 'Rifiutato' : 'Rifiuta'}
                                                </button>
                                              </div>
                                              {other.history.length > 0 && (
                                                <div className="sharing-history">
                                                  <button
                                                    className="sharing-history-toggle"
                                                    onClick={() =>
                                                      setExpandedHistory((prev) => ({
                                                        ...prev,
                                                        [msgKey]: !prev[msgKey],
                                                      }))
                                                    }
                                                  >
                                                    {expandedHistory[msgKey] ? '▾' : '▸'} Cronologia ({other.history.length})
                                                  </button>
                                                  {expandedHistory[msgKey] && (
                                                    <ul className="sharing-history-list">
                                                      {other.history.map((h, idx) => (
                                                        <li key={idx} className="sharing-history-entry">
                                                          <span className="sharing-history-who">
                                                            {h.from_username === other.username ? other.username : 'tu'}
                                                          </span>
                                                          <span className={`sharing-history-state sharing-history-state-${h.state}`}>
                                                            {SHARING_STATE_LABELS[h.state]}
                                                          </span>
                                                          <span className="sharing-history-date">{formatHistoryDate(h.decided_at)}</span>
                                                          {h.message && (
                                                            <div className="sharing-history-message">"{h.message}"</div>
                                                          )}
                                                        </li>
                                                      ))}
                                                    </ul>
                                                  )}
                                                </div>
                                              )}
                                            </div>
                                          );
                                        })}
                                      </div>
                                    )}
                                    {sharingError[row.id] && (
                                      <div className="archive-contact-result sharing-error">{sharingError[row.id]}</div>
                                    )}
                                  </div>
                                )}
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                    {data && data.results.length === 0 && (
                      <tr>
                        <td colSpan={6} className="archive-empty">
                          Nessuna stringa trovata con questi filtri.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              {data && data.total > 0 && (
                <div className="archive-pagination">
                  <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                    Precedente
                  </button>
                  <span>
                    Pagina {page} di {totalPages}
                  </span>
                  <button disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
                    Successiva
                  </button>
                </div>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
};

export default ArchivePanel;
