/**
 * Carte des pylônes avec rayons d'influence (zones de couverture).
 */
(function () {
    'use strict';

    const PYLON_COLOR = '#e65100';
    let map = null;
    let layerGroup = null;
    let lastItems = null;

    function formatNumber(value, decimals) {
        if (value == null || Number.isNaN(value)) return '—';
        return Number(value).toLocaleString('fr-FR', {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals,
        });
    }

    function formatAreaHa(ha) {
        if (ha == null) return '—';
        if (ha >= 1) return `${formatNumber(ha, ha >= 100 ? 1 : 2)} ha`;
        const m2 = ha * 10000;
        if (m2 >= 1000000) return `${formatNumber(m2 / 1000000, 2)} km²`;
        return `${formatNumber(m2, 0)} m²`;
    }

    function parseJsonField(value) {
        if (!value) return null;
        if (typeof value === 'object') return value;
        try {
            return JSON.parse(value);
        } catch (e) {
            return null;
        }
    }

    function pylonFromItem(item) {
        const raw = item.raw || item;
        let lat = raw.latitude != null ? Number(raw.latitude) : null;
        let lng = raw.longitude != null ? Number(raw.longitude) : null;

        const geom = parseJsonField(raw.geometry);
        if ((lat == null || lng == null) && geom?.type === 'Point' && geom.coordinates?.length >= 2) {
            lng = Number(geom.coordinates[0]);
            lat = Number(geom.coordinates[1]);
        }

        let radius = Number(raw.radius_m) || 0;
        if (!radius) {
            const props = parseJsonField(raw.properties);
            radius = Number(props?.radius_m) || 0;
        }
        if (!radius) radius = 500;

        const areaM2 = Math.PI * radius * radius;
        return {
            id: raw.id || item.id,
            code_unique: raw.code_unique || item.code,
            nom: raw.nom || item.nom,
            latitude: lat,
            longitude: lng,
            radius_m: radius,
            coverage_area_m2: areaM2,
            coverage_area_ha: areaM2 / 10000,
        };
    }

    function buildClientSummary(pylons) {
        const located = pylons.filter((p) => p.latitude != null && p.longitude != null);
        const radii = pylons.map((p) => p.radius_m).filter((r) => r > 0);
        const totalIndividual = pylons.reduce((sum, p) => sum + (p.coverage_area_m2 || 0), 0);
        return {
            count: pylons.length,
            located_count: located.length,
            avg_radius_m: radii.length ? radii.reduce((a, b) => a + b, 0) / radii.length : null,
            total_individual_area_m2: totalIndividual,
            total_individual_area_ha: totalIndividual / 10000,
            union_coverage_area_m2: totalIndividual,
            union_coverage_area_ha: totalIndividual / 10000,
            overlap_area_m2: 0,
            overlap_area_ha: 0,
        };
    }

    function isGeoTabVisible() {
        const section = document.getElementById('poiViewGeo');
        const statsSection = document.getElementById('theme-infrastructures');
        if (statsSection && statsSection.offsetParent !== null) return true;
        return section && !section.hidden;
    }

    function ensureMap() {
        const el = document.getElementById('pylonCoverageMap');
        if (!el) return null;
        if (!window.L) {
            console.error('Leaflet non chargé (pylon-coverage-map)');
            return null;
        }

        if (!map) {
            map = L.map(el, { zoomControl: true, scrollWheelZoom: true });
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19,
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
            }).addTo(map);
            layerGroup = L.layerGroup().addTo(map);
        }

        return map;
    }

    function invalidateSize(delayMs) {
        if (!map) return;
        const delay = typeof delayMs === 'number' ? delayMs : 150;
        setTimeout(() => {
            if (map) map.invalidateSize({ animate: false });
        }, delay);
    }

    function renderSummary(summary) {
        const el = document.getElementById('pylonCoverageSummary');
        if (!el || !summary) return;

        const unionHa = summary.union_coverage_area_ha;
        const individualHa = summary.total_individual_area_ha;
        const overlapHa = summary.overlap_area_ha;
        const hasOverlap = overlapHa != null && overlapHa > 0.0001;

        el.innerHTML = `
            <div class="pylon-coverage-metric">
                <span class="pylon-coverage-metric-value">${summary.count}</span>
                <span class="pylon-coverage-metric-label">Pylône${summary.count > 1 ? 's' : ''}</span>
            </div>
            <div class="pylon-coverage-metric">
                <span class="pylon-coverage-metric-value">${formatNumber(summary.avg_radius_m, 0)} m</span>
                <span class="pylon-coverage-metric-label">Rayon moyen</span>
            </div>
            <div class="pylon-coverage-metric">
                <span class="pylon-coverage-metric-value">${formatAreaHa(unionHa)}</span>
                <span class="pylon-coverage-metric-label">Zone couverte (net)</span>
            </div>
            <div class="pylon-coverage-metric">
                <span class="pylon-coverage-metric-value">${formatAreaHa(individualHa)}</span>
                <span class="pylon-coverage-metric-label">Somme des cercles</span>
            </div>
            ${hasOverlap ? `
            <div class="pylon-coverage-metric pylon-coverage-metric-overlap">
                <span class="pylon-coverage-metric-value">${formatAreaHa(overlapHa)}</span>
                <span class="pylon-coverage-metric-label">Chevauchements</span>
            </div>` : ''}
            <div class="pylon-coverage-metric">
                <span class="pylon-coverage-metric-value">${summary.located_count} / ${summary.count}</span>
                <span class="pylon-coverage-metric-label">Localisés</span>
            </div>
        `;
    }

    function renderMap(pylons, showCoverage) {
        if (!isGeoTabVisible()) return;

        ensureMap();
        if (!map || !layerGroup) return;

        layerGroup.clearLayers();
        const bounds = [];

        pylons.forEach((pylon) => {
            const lat = pylon.latitude;
            const lng = pylon.longitude;
            const radius = pylon.radius_m;
            if (lat == null || lng == null || Number.isNaN(lat) || Number.isNaN(lng)) return;

            bounds.push([lat, lng]);

            if (showCoverage && radius > 0) {
                const circle = L.circle([lat, lng], {
                    radius: Number(radius),
                    color: PYLON_COLOR,
                    weight: 2,
                    dashArray: '6 4',
                    fillColor: PYLON_COLOR,
                    fillOpacity: 0.15,
                });
                circle.bindPopup(`
                    <strong>${pylon.nom || pylon.code_unique || 'Pylône'}</strong><br>
                    Rayon : ${formatNumber(radius, 0)} m<br>
                    Couverture : ${formatAreaHa(pylon.coverage_area_ha)}<br>
                    ${pylon.code_unique ? `<small>${pylon.code_unique}</small>` : ''}
                `);
                layerGroup.addLayer(circle);
            }

            const marker = L.marker([lat, lng], {
                icon: L.divIcon({
                    className: 'map-feature-marker pylon',
                    html: `<div style="background:${PYLON_COLOR};width:24px;height:24px;border-radius:50%;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;font-size:13px;">🗼</div>`,
                    iconSize: [24, 24],
                    iconAnchor: [12, 12],
                }),
            });
            marker.bindPopup(`
                <strong>${pylon.nom || 'Pylône'}</strong><br>
                ${pylon.code_unique ? `${pylon.code_unique}<br>` : ''}
                Rayon : ${formatNumber(radius, 0)} m
            `);
            layerGroup.addLayer(marker);
        });

        invalidateSize(50);

        if (bounds.length === 1) {
            map.setView(bounds[0], 13);
        } else if (bounds.length > 1) {
            map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
        } else if (window.GeoTaxCountry) {
            GeoTaxCountry.centerMap(map);
        } else {
            map.setView([0.5, 18.0], 4);
        }

        invalidateSize(300);
    }

    function renderAnalysis(coverageData, options) {
        const panel = document.getElementById('pylonMapPanel')
            || document.getElementById('statsPylonMapPanel');
        if (!panel || !coverageData) return;

        const opts = options || {};
        const showCoverage = opts.showCoverage !== false;
        const summary = coverageData.summary || {};
        const pylons = coverageData.pylons || [];

        if (!summary.count && !pylons.length) {
            panel.hidden = true;
            return;
        }

        panel.hidden = false;
        renderSummary(summary);
        renderMap(pylons, showCoverage);
    }

    async function update(items, options) {
        const panel = document.getElementById('pylonMapPanel');
        if (!panel) return;

        lastItems = items;
        const opts = options || {};
        const showCoverage = opts.showCoverage !== false;
        const filtered = (items || []).filter(
            (p) => p.shapeId === 'pylon' || p.raw?.feature_type === 'pylon',
        );

        if (!filtered.length) {
            panel.hidden = true;
            return;
        }

        panel.hidden = false;
        const clientPylons = filtered.map(pylonFromItem);
        const clientSummary = buildClientSummary(clientPylons);

        renderSummary(clientSummary);
        renderMap(clientPylons, showCoverage);

        const ids = filtered.map((p) => p.id).join(',');
        try {
            const res = await fetch(`/api/pylons/coverage?ids=${encodeURIComponent(ids)}`);
            if (!res.ok) throw new Error(`API ${res.status}`);
            const data = await res.json();
            if (data.summary) renderSummary(data.summary);
            if (Array.isArray(data.pylons) && data.pylons.length) {
                renderMap(data.pylons, showCoverage);
            }
            if (typeof opts.onSummary === 'function') {
                opts.onSummary(data.summary);
            }
        } catch (err) {
            console.warn('API couverture pylônes indisponible, affichage local :', err);
        }
    }

    function refresh() {
        if (lastItems) {
            return update(lastItems, { showCoverage: isCoverageVisible() });
        }
    }

    function isCoverageVisible() {
        const cb = document.getElementById('pylonShowCoverage');
        return !cb || cb.checked;
    }

    function bindControls(getFilteredItems) {
        const cb = document.getElementById('pylonShowCoverage');
        if (cb && !cb.dataset.bound) {
            cb.dataset.bound = '1';
            cb.addEventListener('change', () => {
                const items = typeof getFilteredItems === 'function' ? getFilteredItems() : [];
                update(items, { showCoverage: cb.checked });
            });
        }
    }

    window.PylonCoverageMap = {
        update,
        renderAnalysis,
        refresh,
        invalidateSize,
        bindControls,
        isCoverageVisible,
    };
})();
