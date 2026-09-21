/**
 * Contexte pays GeoTax — sélection globale (session + localStorage).
 */
(function () {
    'use strict';

    const STORAGE_KEY = 'geotax-selected-pays-id';
    const DEFAULT_MAP_VIEW = { lat: 0.5, lng: 18.0, zoom: 4 };
    let currentPaysId = null;
    let currentMapView = { ...DEFAULT_MAP_VIEW };
    let initialized = false;

    function parseId(value) {
        if (value == null || value === '') return null;
        const n = parseInt(value, 10);
        return Number.isNaN(n) ? null : n;
    }

    function applySessionData(data) {
        if (data?.map_view) {
            currentMapView = data.map_view;
        } else if (data?.pays?.map_view) {
            currentMapView = data.pays.map_view;
        }
    }

    function getId() {
        return currentPaysId;
    }

    function getMapView() {
        return currentMapView || { ...DEFAULT_MAP_VIEW };
    }

    function setLocalId(paysId) {
        currentPaysId = paysId;
        try {
            if (paysId) {
                localStorage.setItem(STORAGE_KEY, String(paysId));
            } else {
                localStorage.removeItem(STORAGE_KEY);
            }
        } catch (e) { /* ignore */ }
    }

    function appendQuery(url) {
        if (!currentPaysId) return url;
        const sep = url.includes('?') ? '&' : '?';
        return `${url}${sep}pays_id=${encodeURIComponent(currentPaysId)}`;
    }

    function withParams(params) {
        const out = params instanceof URLSearchParams
            ? new URLSearchParams(params)
            : new URLSearchParams(params || {});
        if (currentPaysId) {
            out.set('pays_id', String(currentPaysId));
        }
        return out;
    }

    function dispatchChange(paysId, pays, mapView) {
        document.dispatchEvent(new CustomEvent('geotax:pays-changed', {
            detail: {
                paysId,
                pays,
                mapView: mapView || getMapView(),
            },
        }));
    }

    function centerMap(map, options) {
        if (!map || !window.L) return;
        const view = getMapView();
        const animate = options?.animate !== false;
        const padding = options?.padding || [40, 40];
        const maxZoom = options?.maxZoom || view.zoom || 14;

        if (view.bounds && view.bounds.length === 2) {
            map.fitBounds(view.bounds, { padding, maxZoom, animate });
            return;
        }
        map.setView([view.lat, view.lng], view.zoom || 6, { animate });
    }

    async function syncToSession(paysId) {
        const response = await fetch('/api/session/pays', {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pays_id: paysId }),
        });
        if (!response.ok) {
            throw new Error('Impossible de définir le pays');
        }
        return response.json();
    }

    async function setId(paysId, options) {
        const opts = options || {};
        const id = parseId(paysId);
        setLocalId(id);
        if (opts.sync !== false) {
            const data = await syncToSession(id);
            if (data.pays_id !== undefined) {
                setLocalId(data.pays_id);
            }
            applySessionData(data);
            dispatchChange(getId(), data.pays || null, getMapView());
            return data;
        }
        dispatchChange(getId(), null, getMapView());
        return { pays_id: getId() };
    }

    async function loadFromSession() {
        const response = await fetch('/api/session/pays', { credentials: 'include' });
        if (!response.ok) {
            throw new Error('Session pays indisponible');
        }
        const data = await response.json();
        const localId = parseId(localStorage.getItem(STORAGE_KEY));
        const sessionId = parseId(data.pays_id);

        if (localId && localId !== sessionId) {
            try {
                const synced = await setId(localId, { sync: true });
                return synced;
            } catch (e) {
                setLocalId(sessionId);
                applySessionData(data);
            }
        } else {
            setLocalId(sessionId);
            applySessionData(data);
        }
        return data;
    }

    async function populateSelect(selectEl, data) {
        if (!selectEl) return;
        const available = data?.available || [];
        const selected = getId();
        selectEl.innerHTML = '<option value="">🌍 Tous les pays</option>';
        available.forEach((p) => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.nom;
            if (selected && p.id === selected) {
                opt.selected = true;
            }
            selectEl.appendChild(opt);
        });
    }

    async function initHeaderSelect(selectId) {
        const selectEl = document.getElementById(selectId || 'globalPaysSelect');
        if (!selectEl || selectEl.dataset.bound) return;
        selectEl.dataset.bound = '1';

        let data;
        try {
            data = await loadFromSession();
        } catch (e) {
            console.warn('Pays session:', e);
            data = { available: [], map_view: { ...DEFAULT_MAP_VIEW } };
            try {
                const res = await fetch('/api/pays', { credentials: 'include' });
                if (res.ok) {
                    data.available = await res.json();
                }
            } catch (err) { /* ignore */ }
            setLocalId(parseId(localStorage.getItem(STORAGE_KEY)));
        }

        await populateSelect(selectEl, data);

        selectEl.addEventListener('change', async () => {
            const value = selectEl.value;
            selectEl.disabled = true;
            try {
                await setId(value ? parseInt(value, 10) : null);
            } catch (err) {
                console.error(err);
                alert('Erreur lors du changement de pays.');
            } finally {
                selectEl.disabled = false;
            }
        });

        initialized = true;
    }

    async function fillSelect(selectEl, selectedId) {
        if (!selectEl) return;
        let available = [];
        try {
            const res = await fetch('/api/pays', { credentials: 'include' });
            if (res.ok) available = await res.json();
        } catch (e) { /* ignore */ }

        const sid = parseId(selectedId) || getId();
        selectEl.innerHTML = '<option value="">Sélectionner un pays</option>';
        available.forEach((p) => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.nom;
            if (sid && p.id === sid) opt.selected = true;
            selectEl.appendChild(opt);
        });
    }

    window.GeoTaxCountry = {
        initHeaderSelect,
        loadFromSession,
        getId,
        getMapView,
        centerMap,
        setId,
        appendQuery,
        withParams,
        fillSelect,
        onChange(callback) {
            document.addEventListener('geotax:pays-changed', (e) => {
                callback(
                    e.detail?.paysId ?? null,
                    e.detail?.pays ?? null,
                    e.detail?.mapView ?? null,
                );
            });
        },
        isInitialized: () => initialized,
    };

    document.addEventListener('DOMContentLoaded', () => {
        if (document.getElementById('globalPaysSelect')) {
            initHeaderSelect('globalPaysSelect');
        }
    });
})();
