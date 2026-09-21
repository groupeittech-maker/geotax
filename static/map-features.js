/**
 * Entités géographiques avancées GeoTax (pylône, pipeline, parcelle, périmètre).
 */
window.GeoTaxMapFeatures = (function () {
    const TYPE_STYLES = {
        pylon: { fillOpacity: 0.15 },
        pipeline: { fillOpacity: 0 },
        parcel: { fillOpacity: 0.28 },
        perimeter: { fillOpacity: 0.12 },
    };

    let loadedActivityTypes = {};

    let map = null;
    let layerGroups = {};
    let featureLayers = {};
    let drawControl = null;
    let activeDrawHandler = null;
    let currentDrawType = null;
    let pendingLayer = null;
    let pendingGeometry = null;
    let visibleTypes = new Set(['pylon', 'pipeline', 'parcel', 'perimeter']);
    let onCountsUpdate = null;
    let onDrawComplete = null;
    let traceState = null;
    let typesCommerceById = {};
    let typesCommerceLoaded = false;

    function getEffectiveChamps(tc) {
        if (!tc) return [];
        return tc.champs_effectifs || tc.champs || [];
    }

    function mapFeatureFieldDomId(typeId, ch) {
        const code = typeof ch === 'string' ? ch : (ch.code || 'field');
        const id = (typeof ch === 'object' && ch.id) ? ch.id : code;
        return `mf_tech_${typeId}_${id}`;
    }

    async function ensureTypesCommerceLoaded() {
        if (typesCommerceLoaded) return;
        try {
            const response = await fetch('/api/types-commerce?include_champs=true', { credentials: 'include' });
            const types = await response.json();
            typesCommerceById = {};
            (types || []).forEach(t => { typesCommerceById[t.id] = t; });
            const select = document.getElementById('mapFeatureTypeCommerce');
            if (select) {
                const current = select.value;
                select.innerHTML = '<option value="">— Aucun —</option>';
                (types || []).forEach(t => {
                    const opt = document.createElement('option');
                    opt.value = t.id;
                    opt.textContent = `${t.nom} (${t.code})`;
                    select.appendChild(opt);
                });
                if (current) select.value = current;
                select.onchange = () => buildMapFeatureTechFields();
            }
            typesCommerceLoaded = true;
        } catch (e) {
            console.error('Erreur chargement types commerce (carte):', e);
        }
    }

    function buildMapFeatureTechFields(existingData) {
        const container = document.getElementById('mapFeatureTechFields');
        const select = document.getElementById('mapFeatureTypeCommerce');
        if (!container || !select) return;
        container.innerHTML = '';
        const typeId = select.value ? parseInt(select.value, 10) : null;
        const tc = typeId ? typesCommerceById[typeId] : null;
        const champs = getEffectiveChamps(tc);
        if (!tc || !champs.length) return;

        const title = document.createElement('p');
        title.className = 'map-feature-tech-title';
        title.textContent = 'Données techniques';
        container.appendChild(title);

        const grid = document.createElement('div');
        grid.className = 'form-grid poi-admin-grid';
        champs.forEach(ch => {
            const group = document.createElement('div');
            group.className = 'form-group';
            const label = document.createElement('label');
            const domId = mapFeatureFieldDomId(typeId, ch);
            label.setAttribute('for', domId);
            label.textContent = ch.libelle;
            group.appendChild(label);

            const type = ch.type_champ || 'str';
            let input;
            if (type === 'textarea') {
                input = document.createElement('textarea');
                input.rows = 2;
            } else if (type === 'checkbox') {
                input = document.createElement('input');
                input.type = 'checkbox';
            } else {
                input = document.createElement('input');
                if (type === 'int') { input.type = 'number'; input.min = '0'; input.step = '1'; }
                else if (type === 'float') { input.type = 'number'; input.min = '0'; input.step = 'any'; }
                else if (type === 'date') input.type = 'date';
                else if (type === 'time') input.type = 'time';
                else if (type === 'email') input.type = 'email';
                else if (type === 'tel') input.type = 'tel';
                else if (type === 'url') input.type = 'url';
                else input.type = 'text';
            }
            input.id = domId;
            input.dataset.fieldCode = ch.code;
            input.dataset.fieldType = type;
            if (ch.placeholder && input.type !== 'checkbox') input.placeholder = ch.placeholder;
            if (existingData && existingData[ch.code] != null && existingData[ch.code] !== '') {
                if (type === 'checkbox') {
                    input.checked = existingData[ch.code] === true || existingData[ch.code] === 'true' || existingData[ch.code] === 1;
                } else {
                    input.value = existingData[ch.code];
                }
            }
            group.appendChild(input);
            grid.appendChild(group);
        });
        container.appendChild(grid);
    }

    function collectMapFeatureDonneesAdministratives() {
        const select = document.getElementById('mapFeatureTypeCommerce');
        if (!select || !select.value) return null;
        const typeId = parseInt(select.value, 10);
        const tc = typesCommerceById[typeId];
        if (!tc) return null;
        const out = {};
        getEffectiveChamps(tc).forEach(ch => {
            const domId = mapFeatureFieldDomId(typeId, ch);
            const el = document.getElementById(domId);
            if (!el) return;
            const type = ch.type_champ || 'str';
            if (type === 'checkbox') {
                if (el.checked) out[ch.code] = true;
                return;
            }
            const v = (el.value || '').trim();
            if (v !== '') out[ch.code] = v;
        });
        return Object.keys(out).length ? out : {};
    }

    function setDrawCompleteHandler(handler) {
        onDrawComplete = typeof handler === 'function' ? handler : null;
    }

    function latLngsToPolygonRing(latlngs) {
        const ring = latlngs.map(ll => [ll.lng, ll.lat]);
        if (ring.length && (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1])) {
            ring.push(ring[0]);
        }
        return ring;
    }

    function stopTrace() {
        if (traceState?.clickHandler && map) {
            map.off('click', traceState.clickHandler);
        }
        if (traceState?.previewLayer && map) {
            map.removeLayer(traceState.previewLayer);
        }
        if (traceState?.closureLayer && map) {
            map.removeLayer(traceState.closureLayer);
        }
        if (traceState?.pointMarkers?.length && map) {
            traceState.pointMarkers.forEach(m => map.removeLayer(m));
        }
        traceState = null;
        map?.getContainer()?.classList.remove('map-trace-mode');
    }

    function isPolygonTrace(featureType) {
        return featureType === 'parcel' || featureType === 'perimeter';
    }

    function tracePointRole(index, featureType, total, hasEndPoint) {
        if (index === 0) return 'start';
        if (!isPolygonTrace(featureType) && hasEndPoint && index === total - 1) return 'end';
        return 'waypoint';
    }

    function traceMarkerStyle(role, featureType) {
        const colors = {
            start: { fill: '#2196F3', border: '#fff', label: 'D' },
            end: { fill: '#e53935', border: '#fff', label: 'A' },
            waypoint: { fill: '#ff9800', border: '#fff', label: '' },
        };
        if (isPolygonTrace(featureType) && role === 'waypoint') {
            return { fill: '#2e7d32', border: '#fff', label: '' };
        }
        return colors[role] || colors.waypoint;
    }

    function refreshTraceMarkers() {
        if (!traceState || !map) return;
        const { latlngs, featureType, hasEndPoint } = traceState;
        traceState.pointMarkers.forEach(m => map.removeLayer(m));
        traceState.pointMarkers = latlngs.map((ll, i) => {
            const role = tracePointRole(i, featureType, latlngs.length, hasEndPoint);
            const style = traceMarkerStyle(role, featureType);
            const label = style.label || String(i + 1);
            return L.marker(ll, {
                icon: L.divIcon({
                    className: 'trace-point-marker',
                    html: `<div class="trace-point-marker-dot" style="background:${style.fill};border:2px solid ${style.border};" title="${role}">${label}</div>`,
                    iconSize: [22, 22],
                    iconAnchor: [11, 11],
                }),
                draggable: true,
            }).addTo(map);
        });
        traceState.pointMarkers.forEach((marker, i) => {
            marker.on('dragend', () => {
                traceState.latlngs[i] = marker.getLatLng();
                updateTracePreview();
                notifyTraceUpdate();
            });
        });
    }

    function updateTracePreview() {
        if (!traceState) return;
        const { featureType, latlngs, previewLayer, closureLayer } = traceState;

        if (isPolygonTrace(featureType)) {
            previewLayer.setLatLngs(latlngs);
            if (closureLayer && latlngs.length >= 2) {
                closureLayer.setLatLngs([latlngs[latlngs.length - 1], latlngs[0]]);
                closureLayer.setStyle({ opacity: latlngs.length >= 3 ? 0.85 : 0.55 });
            } else if (closureLayer) {
                closureLayer.setLatLngs([]);
            }
        } else {
            previewLayer.setLatLngs(latlngs);
        }
        refreshTraceMarkers();
    }

    function notifyTraceUpdate() {
        if (typeof traceState?.onPointsUpdate === 'function') {
            traceState.onPointsUpdate(traceState.latlngs.length, getTracePointsInfo());
        }
    }

    function addTracePoint(lat, lng, role) {
        if (!traceState) return false;
        const ll = L.latLng(lat, lng);
        const { featureType } = traceState;

        if (isPolygonTrace(featureType)) {
            traceState.latlngs.push(ll);
        } else if (role === 'end') {
            if (traceState.hasEndPoint) {
                traceState.latlngs[traceState.latlngs.length - 1] = ll;
            } else {
                traceState.latlngs.push(ll);
                traceState.hasEndPoint = true;
            }
        } else {
            if (traceState.hasEndPoint) {
                traceState.latlngs.splice(traceState.latlngs.length - 1, 0, ll);
            } else {
                traceState.latlngs.push(ll);
            }
        }

        updateTracePreview();
        notifyTraceUpdate();
        return true;
    }

    function getTracePointsInfo() {
        if (!traceState) return [];
        const { latlngs, featureType, hasEndPoint } = traceState;
        return latlngs.map((ll, i) => ({
            index: i,
            lat: ll.lat,
            lng: ll.lng,
            role: tracePointRole(i, featureType, latlngs.length, hasEndPoint),
        }));
    }

    function removeTracePointAt(index) {
        if (!traceState || index <= 0 || index >= traceState.latlngs.length) return false;
        const isLast = index === traceState.latlngs.length - 1;
        traceState.latlngs.splice(index, 1);
        if (isLast && !isPolygonTrace(traceState.featureType)) {
            traceState.hasEndPoint = false;
        }
        updateTracePreview();
        notifyTraceUpdate();
        return true;
    }

    function startTraceFromOrigin(featureType, originLatLng, options) {
        if (!map || !TYPE_STYLES[featureType]) return;
        stopDraw();
        stopTrace();

        const traceColor = '#607d8b';
        const origin = L.latLng(originLatLng.lat, originLatLng.lng);
        const latlngs = [origin];
        let previewLayer = null;
        let closureLayer = null;

        if (featureType === 'pipeline') {
            previewLayer = L.polyline(latlngs, {
                color: traceColor,
                weight: 5,
                dashArray: '8 6',
                opacity: 0.9,
            }).addTo(map);
        } else if (isPolygonTrace(featureType)) {
            previewLayer = L.polyline(latlngs, {
                color: traceColor,
                weight: 3,
                dashArray: '8 6',
                opacity: 0.9,
            }).addTo(map);
            closureLayer = L.polyline([], {
                color: traceColor,
                weight: 2,
                dashArray: '4 8',
                opacity: 0.5,
            }).addTo(map);
        } else {
            return;
        }

        const clickHandler = (e) => {
            if (isPolygonTrace(featureType)) {
                addTracePoint(e.latlng.lat, e.latlng.lng, 'waypoint');
            } else if (traceState.hasEndPoint) {
                addTracePoint(e.latlng.lat, e.latlng.lng, 'waypoint');
            } else if (traceState.latlngs.length === 1) {
                addTracePoint(e.latlng.lat, e.latlng.lng, 'end');
            } else {
                addTracePoint(e.latlng.lat, e.latlng.lng, 'waypoint');
            }
        };

        map.on('click', clickHandler);
        map.getContainer().classList.add('map-trace-mode');

        traceState = {
            featureType,
            latlngs,
            previewLayer,
            closureLayer,
            pointMarkers: [],
            clickHandler,
            onComplete: options?.onComplete || null,
            onPointsUpdate: options?.onPointsUpdate || null,
            hasEndPoint: false,
        };
        updateTracePreview();
        notifyTraceUpdate();
    }

    function undoTracePoint() {
        if (!traceState || traceState.latlngs.length <= 1) return traceState?.latlngs.length || 0;
        traceState.latlngs.pop();
        if (!isPolygonTrace(traceState.featureType)) {
            traceState.hasEndPoint = false;
        }
        updateTracePreview();
        notifyTraceUpdate();
        return traceState.latlngs.length;
    }

    function finishTrace() {
        if (!traceState) return false;
        const { featureType, latlngs, previewLayer, onComplete } = traceState;
        const isPolygon = isPolygonTrace(featureType);
        const minPoints = featureType === 'pipeline' ? 2 : 3;

        if (latlngs.length < minPoints) {
            const extra = minPoints - latlngs.length;
            const hint = isPolygon
                ? `Ajoutez encore ${extra} sommet(s) — le polygone se fermera automatiquement sur le départ.`
                : `Définissez le point d'arrivée (GPS ou clic carte) — il manque ${extra} point(s).`;
            alert(hint);
            return false;
        }

        if (featureType === 'pipeline' && !traceState.hasEndPoint && latlngs.length >= 2) {
            traceState.hasEndPoint = true;
        }

        let geometry;
        if (featureType === 'pipeline') {
            geometry = {
                type: 'LineString',
                coordinates: latlngs.map(ll => [ll.lng, ll.lat]),
            };
        } else {
            geometry = {
                type: 'Polygon',
                coordinates: [latLngsToPolygonRing(latlngs)],
            };
        }

        const layer = previewLayer;
        stopTrace();
        if (typeof onComplete === 'function') {
            onComplete(featureType, geometry, layer);
        }
        return true;
    }

    function getTracePointCount() {
        return traceState ? traceState.latlngs.length : 0;
    }

    function latLngsToLineCoords(latlngs) {
        return latlngs.map(ll => [ll.lng, ll.lat]);
    }

    function latLngsToPolygonCoords(latlngs) {
        const ring = latLngsToLineCoords(Array.isArray(latlngs[0]) ? latlngs[0] : latlngs);
        if (ring.length && (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1])) {
            ring.push(ring[0]);
        }
        return ring;
    }

    function layerToGeometry(layer, featureType) {
        if (featureType === 'pylon') {
            const ll = layer.getLatLng();
            return { type: 'Point', coordinates: [ll.lng, ll.lat] };
        }
        if (featureType === 'pipeline') {
            return {
                type: 'LineString',
                coordinates: latLngsToLineCoords(layer.getLatLngs()),
            };
        }
        const ring = latLngsToPolygonCoords(layer.getLatLngs());
        return { type: 'Polygon', coordinates: [ring] };
    }

    function formatMetric(feature) {
        const p = feature.properties || {};
        const parts = [];
        if (p.radius_m) parts.push(`Rayon : ${Math.round(p.radius_m)} m`);
        if (p.length_m) parts.push(`Longueur : ${(p.length_m / 1000).toFixed(2)} km`);
        if (p.area_ha) parts.push(`Surface : ${p.area_ha.toFixed(3)} ha`);
        if (p.perimeter_m) parts.push(`Périmètre : ${Math.round(p.perimeter_m)} m`);
        const props = p.properties || {};
        if (props.diameter_mm) parts.push(`Ø ${props.diameter_mm} mm`);
        return parts.join(' · ') || '';
    }

    function buildPopup(props) {
        const metrics = formatMetric({ properties: props });
        const validation = props.statut_validation || 'brouillon';
        const catLabel = props.categorie === 'infrastructure' ? 'Infrastructure' : 'Contribuable';
        const displayName = props.name || props.nom || '—';
        return `
            <div class="popup-content map-feature-popup">
                <div class="popup-title">${props.feature_type_icon || ''} ${displayName}</div>
                <div class="popup-info"><strong>Code:</strong> ${props.code_unique}</div>
                <div class="popup-info"><strong>Catégorie:</strong> ${catLabel}</div>
                <div class="popup-info"><strong>Forme:</strong> ${props.feature_type_label || props.feature_type}</div>
                ${props.type_commerce?.nom ? `<div class="popup-info"><strong>Activité:</strong> ${props.type_commerce.nom}</div>` : ''}
                ${props.description ? `<div class="popup-info">${props.description}</div>` : ''}
                ${metrics ? `<div class="popup-info popup-metrics">${metrics}</div>` : ''}
                <div class="popup-info"><strong>Validation:</strong> ${validation}</div>
                <div class="popup-actions">
                    <button type="button" class="map-popup-edit-btn" onclick="editMapFeature(${props.id})">✏️ Modifier</button>
                    <button type="button" class="map-popup-delete-btn" onclick="deleteMapFeature(${props.id})">🗑️ Supprimer</button>
                </div>
            </div>
        `;
    }

    function resolveActivityColor(props) {
        if (props.display_color) return props.display_color;
        const tc = props.type_commerce;
        if (tc?.color) return tc.color;
        if (tc?.secteur?.color) return tc.secteur.color;
        return '#607d8b';
    }

    function resolveFeatureStyle(props, featureType) {
        if (window.GeoTaxMapStyles) {
            const s = GeoTaxMapStyles.resolveStyleFromProps(props);
            return {
                color: s.color,
                lineStyle: s.lineStyle,
                fillPattern: s.fillPattern,
                fillOpacity: GeoTaxMapStyles.getFillOpacity(s.fillPattern, featureType),
                dashArray: GeoTaxMapStyles.getLineDashArray(s.lineStyle),
            };
        }
        const shapeStyle = TYPE_STYLES[featureType] || { fillOpacity: 0.2 };
        return {
            color: resolveActivityColor(props),
            lineStyle: 'solid',
            fillPattern: 'solid',
            fillOpacity: shapeStyle.fillOpacity ?? 0.2,
            dashArray: null,
        };
    }

    function trackActivityType(props) {
        const tc = props.type_commerce;
        if (tc && tc.id) {
            loadedActivityTypes[tc.id] = tc;
        }
    }

    function getLoadedActivityTypes() {
        return Object.values(loadedActivityTypes);
    }

    function bindFeaturePopup(layer, props) {
        const content = buildPopup(props);
        if (layer.getLayers) {
            layer.getLayers().forEach(child => {
                if (child.bindPopup) child.bindPopup(content);
            });
            return;
        }
        if (layer.bindPopup) layer.bindPopup(content);
    }

    function renderPylon(feature, props, style) {
        const geom = feature.geometry;
        if (!geom || geom.type !== 'Point') return null;
        const [lng, lat] = geom.coordinates;
        const radius = props.radius_m || (props.properties && props.properties.radius_m) || 500;
        const group = L.layerGroup();
        const marker = L.marker([lat, lng], {
            icon: L.divIcon({
                className: 'map-feature-marker pylon',
                html: `<div style="background:${style.color};width:22px;height:22px;border-radius:50%;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;font-size:12px;">🗼</div>`,
                iconSize: [22, 22],
                iconAnchor: [11, 11],
            }),
        });
        const circle = L.circle([lat, lng], {
            radius: Number(radius),
            color: style.color,
            weight: 2,
            dashArray: style.dashArray || '6 4',
            fillColor: style.color,
            fillOpacity: style.fillOpacity ?? 0.15,
            interactive: true,
        });
        if (map && window.GeoTaxMapStyles) {
            GeoTaxMapStyles.applyPathStyle(circle, {
                color: style.color,
                lineStyle: style.lineStyle,
                fillPattern: style.fillPattern,
            }, 'pylon');
        }
        group.addLayer(circle);
        group.addLayer(marker);
        bindFeaturePopup(group, props);
        return group;
    }

    function renderPipeline(feature, props, style) {
        const geom = feature.geometry;
        if (!geom) return null;
        const latlngs = (geom.type === 'LineString' ? geom.coordinates : (geom.coordinates[0] || []))
            .map(c => [c[1], c[0]]);
        if (latlngs.length < 2) return null;
        const diameter = (props.properties && props.properties.diameter_mm) || 400;
        const weight = Math.max(4, Math.min(14, Number(diameter) / 40));
        const line = L.polyline(latlngs, {
            color: style.color,
            weight,
            opacity: 0.85,
            dashArray: style.dashArray || null,
        });
        if (map && window.GeoTaxMapStyles) {
            GeoTaxMapStyles.applyPathStyle(line, {
                color: style.color,
                lineStyle: style.lineStyle,
                fillPattern: 'none',
            }, 'pipeline');
        }
        line.bindPopup(buildPopup(props));
        return line;
    }

    function renderPolygon(feature, props, style, featureType) {
        const geom = feature.geometry;
        if (!geom) return null;
        const layer = L.geoJSON(feature, {
            style: {
                color: style.color,
                weight: 2,
                dashArray: style.dashArray || null,
                fill: style.fillPattern !== 'none',
                fillColor: style.color,
                fillOpacity: style.fillPattern === 'none' ? 0 : 0.01,
            },
            onEachFeature(_feature, subLayer) {
                subLayer.bindPopup(buildPopup(props));
                if (window.GeoTaxMapStyles) {
                    GeoTaxMapStyles.applyPathStyle(subLayer, {
                        color: style.color,
                        lineStyle: style.lineStyle,
                        fillPattern: style.fillPattern,
                    }, featureType);
                }
            },
        });
        return layer;
    }

    function applyPatternStylesRecursive(layer) {
        if (!layer) return;
        if (layer._geotaxPatternApply) {
            requestAnimationFrame(() => layer._geotaxPatternApply());
        }
        if (typeof layer.eachLayer === 'function') {
            layer.eachLayer(sub => applyPatternStylesRecursive(sub));
        }
    }

    function renderFeatureOnMap(geoFeature) {
        const props = geoFeature.properties || {};
        const featureType = props.feature_type;
        if (!visibleTypes.has(featureType)) return;

        trackActivityType(props);
        const style = resolveFeatureStyle(props, featureType);
        let layer = null;
        if (featureType === 'pylon') layer = renderPylon(geoFeature, props, style);
        else if (featureType === 'pipeline') layer = renderPipeline(geoFeature, props, style);
        else if (featureType === 'parcel' || featureType === 'perimeter') {
            layer = renderPolygon(geoFeature, props, style, featureType);
        }
        if (!layer) return;

        featureLayers[props.id] = layer;
        if (layerGroups[featureType]) {
            layerGroups[featureType].addLayer(layer);
        }
        applyPatternStylesRecursive(layer);
    }

    function ensureLayerGroups() {
        Object.keys(TYPE_STYLES).forEach(type => {
            if (!layerGroups[type]) {
                layerGroups[type] = L.layerGroup();
                if (map && visibleTypes.has(type)) {
                    layerGroups[type].addTo(map);
                }
            }
        });
    }

    function clearLayers() {
        Object.values(layerGroups).forEach(g => g.clearLayers());
        featureLayers = {};
        loadedActivityTypes = {};
    }

    function updateTypeVisibility(type, visible) {
        if (visible) visibleTypes.add(type);
        else visibleTypes.delete(type);
        if (!map || !layerGroups[type]) return;
        if (visible) layerGroups[type].addTo(map);
        else map.removeLayer(layerGroups[type]);
    }

    function getBBoxParam(paddingRatio = 0) {
        if (!map) return '';
        const b = map.getBounds();
        const sw = b.getSouthWest();
        const ne = b.getNorthEast();
        if (!paddingRatio) {
            return `${sw.lng},${sw.lat},${ne.lng},${ne.lat}`;
        }
        const latPad = (ne.lat - sw.lat) * paddingRatio;
        const lngPad = (ne.lng - sw.lng) * paddingRatio;
        return `${sw.lng - lngPad},${sw.lat - latPad},${ne.lng + lngPad},${ne.lat + latPad}`;
    }

    let viewportReloadTimer = null;
    let shapesViewportMode = false;
    let shapesLoadInFlight = false;

    function scheduleViewportReload() {
        if (!map || !shapesViewportMode) return;
        if (map._popup && map._popup.isOpen()) return;
        clearTimeout(viewportReloadTimer);
        viewportReloadTimer = setTimeout(() => loadFeatures({ useBbox: true }), 600);
    }

    async function loadFeatures(options = {}) {
        if (!map || shapesLoadInFlight) return [];
        shapesLoadInFlight = true;
        try {
            const types = [...visibleTypes].join(',');
            let url = `/api/map-features?types=${encodeURIComponent(types)}`;
            if (options.useBbox && shapesViewportMode) {
                url += `&bbox=${encodeURIComponent(getBBoxParam(0.35))}`;
            }
            if (window.GeoTaxCountry) {
                url = GeoTaxCountry.appendQuery(url);
            }
            const response = await fetch(url);
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Erreur chargement');

            const features = data.features || [];
            const total = data.meta?.count ?? features.length;
            if (total > 300) {
                shapesViewportMode = true;
            } else {
                shapesViewportMode = false;
            }

            clearLayers();
            features.forEach(renderFeatureOnMap);

            if (typeof onCountsUpdate === 'function') {
                const counts = {};
                features.forEach(f => {
                    const t = f.properties?.feature_type;
                    if (t) counts[t] = (counts[t] || 0) + 1;
                });
                onCountsUpdate(counts, features.length);
            }
            return features;
        } catch (e) {
            console.error('Map features:', e);
            return [];
        } finally {
            shapesLoadInFlight = false;
        }
    }

    function removeDrawControl() {
        if (drawControl && map) {
            map.removeControl(drawControl);
            drawControl = null;
        }
        if (activeDrawHandler) {
            activeDrawHandler.disable();
            activeDrawHandler = null;
        }
    }

    function stopDraw() {
        currentDrawType = null;
        removeDrawControl();
        document.querySelectorAll('.map-geometry-btn').forEach(btn => btn.classList.remove('active'));
    }

    function getDrawOptions(featureType) {
        const base = {
            polygon: false,
            polyline: false,
            marker: false,
            circle: false,
            rectangle: false,
            circlemarker: false,
        };
        if (featureType === 'pylon') base.marker = true;
        if (featureType === 'pipeline') base.polyline = { shapeOptions: { color: '#607d8b' } };
        if (featureType === 'parcel' || featureType === 'perimeter') {
            base.polygon = {
                shapeOptions: {
                    color: '#607d8b',
                    fillOpacity: TYPE_STYLES[featureType]?.fillOpacity ?? 0.2,
                },
            };
        }
        return base;
    }

    async function openSaveModal(featureType, geometry, previewLayer) {
        pendingGeometry = geometry;
        pendingLayer = previewLayer;
        await ensureTypesCommerceLoaded();
        const modal = document.getElementById('mapFeatureModal');
        if (!modal) return;

        document.getElementById('mapFeatureType').value = featureType;
        document.getElementById('mapFeatureTypeLabel').textContent =
            ({ pylon: 'Pylône', pipeline: 'Pipeline', parcel: 'Parcelle', perimeter: 'Périmètre' })[featureType] || featureType;
        document.getElementById('mapFeatureName').value = '';
        document.getElementById('mapFeatureDescription').value = '';
        const tcSelect = document.getElementById('mapFeatureTypeCommerce');
        if (tcSelect) tcSelect.value = '';
        buildMapFeatureTechFields();

        document.getElementById('mapFeaturePylonFields').style.display = featureType === 'pylon' ? 'block' : 'none';
        document.getElementById('mapFeaturePipelineFields').style.display = featureType === 'pipeline' ? 'block' : 'none';

        if (featureType === 'pylon') {
            document.getElementById('mapFeatureRadius').value = '500';
        }
        if (featureType === 'pipeline') {
            document.getElementById('mapFeatureDiameter').value = '400';
        }

        modal.style.display = 'flex';
    }

    function geometryBounds(geometry) {
        if (!geometry || !geometry.coordinates) return null;
        let minLat = Infinity;
        let maxLat = -Infinity;
        let minLng = Infinity;
        let maxLng = -Infinity;

        function visitCoord(coord) {
            const lng = coord[0];
            const lat = coord[1];
            minLat = Math.min(minLat, lat);
            maxLat = Math.max(maxLat, lat);
            minLng = Math.min(minLng, lng);
            maxLng = Math.max(maxLng, lng);
        }

        function walk(coords, depth) {
            if (depth === 0) {
                visitCoord(coords);
                return;
            }
            coords.forEach(c => walk(c, depth - 1));
        }

        if (geometry.type === 'Point') {
            walk(geometry.coordinates, 0);
        } else if (geometry.type === 'LineString') {
            walk(geometry.coordinates, 1);
        } else if (geometry.type === 'Polygon') {
            walk(geometry.coordinates, 2);
        }
        if (!isFinite(minLat)) return null;
        return [[minLat, minLng], [maxLat, maxLng]];
    }

    async function focusFeature(featureId) {
        if (!map) return false;
        const layer = featureLayers[featureId];
        if (layer) {
            if (layer.getBounds) {
                map.fitBounds(layer.getBounds().pad(0.15), { maxZoom: 17 });
            } else if (layer.getLatLng) {
                map.setView(layer.getLatLng(), 16);
            }
            if (layer.openPopup) layer.openPopup();
            else if (layer.getLayers) {
                const first = layer.getLayers()[0];
                if (first?.openPopup) first.openPopup();
            }
            return true;
        }

        try {
            const response = await fetch(`/api/boutiques/${featureId}`, { credentials: 'include' });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'POI introuvable');
            const geom = data.geometry;
            if (geom) {
                const bounds = geometryBounds(geom);
                if (bounds) {
                    map.fitBounds(bounds, { maxZoom: 17, padding: [40, 40] });
                    return true;
                }
            }
            if (data.latitude != null && data.longitude != null) {
                map.setView([data.latitude, data.longitude], 16);
                return true;
            }
        } catch (e) {
            console.warn('focusFeature:', e);
        }
        return false;
    }

    async function openEditModal(featureId) {
        if (typeof window.editMapFeature === 'function') {
            window.editMapFeature(featureId);
            return;
        }
        try {
            await ensureTypesCommerceLoaded();
            const response = await fetch(`/api/map-features/${featureId}`, { credentials: 'include' });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Erreur chargement');

            map?.closePopup();

            const modal = document.getElementById('mapFeatureModal');
            if (!modal) return;

            const featureType = data.feature_type;
            const typeLabels = { pylon: 'Pylône', pipeline: 'Pipeline', parcel: 'Parcelle', perimeter: 'Périmètre' };
            const props = data.properties || {};

            document.getElementById('mapFeatureEditId').value = featureId;
            document.getElementById('mapFeatureType').value = featureType;
            document.getElementById('mapFeatureModalTitle').childNodes[0].textContent = 'Modifier ';
            document.getElementById('mapFeatureTypeLabel').textContent = typeLabels[featureType] || featureType;
            document.getElementById('mapFeatureName').value = data.name || data.nom || '';
            document.getElementById('mapFeatureDescription').value = data.description || '';
            document.getElementById('mapFeatureSaveBtn').textContent = '💾 Enregistrer';

            document.getElementById('mapFeaturePylonFields').style.display = featureType === 'pylon' ? 'block' : 'none';
            document.getElementById('mapFeaturePipelineFields').style.display = featureType === 'pipeline' ? 'block' : 'none';

            if (featureType === 'pylon') {
                document.getElementById('mapFeatureRadius').value = data.radius_m || props.radius_m || 500;
            }
            if (featureType === 'pipeline') {
                document.getElementById('mapFeatureDiameter').value = props.diameter_mm || 400;
            }

            const tcSelect = document.getElementById('mapFeatureTypeCommerce');
            if (tcSelect) {
                tcSelect.value = data.type_commerce_id ? String(data.type_commerce_id) : '';
            }
            const donnees = data.donnees_administratives || props.donnees_administratives || {};
            buildMapFeatureTechFields(donnees);

            pendingGeometry = data.geometry || null;
            modal.style.display = 'flex';
        } catch (e) {
            alert('Impossible de charger : ' + e.message);
        }
    }

    function closeSaveModal(discardPreview) {
        const modal = document.getElementById('mapFeatureModal');
        if (modal) modal.style.display = 'none';
        const editIdEl = document.getElementById('mapFeatureEditId');
        if (editIdEl) editIdEl.value = '';
        const saveBtn = document.getElementById('mapFeatureSaveBtn');
        if (saveBtn) saveBtn.textContent = 'Enregistrer';
        const titleEl = document.getElementById('mapFeatureModalTitle');
        const labelEl = document.getElementById('mapFeatureTypeLabel');
        if (titleEl?.firstChild) titleEl.firstChild.textContent = 'Enregistrer ';
        if (labelEl) labelEl.textContent = '—';
        if (discardPreview && pendingLayer && map) {
            map.removeLayer(pendingLayer);
        }
        pendingLayer = null;
        pendingGeometry = null;
        stopDraw();
    }

    async function savePendingFeature() {
        const editId = document.getElementById('mapFeatureEditId')?.value;
        const featureType = document.getElementById('mapFeatureType').value;
        const name = document.getElementById('mapFeatureName').value.trim();
        const description = document.getElementById('mapFeatureDescription').value.trim();
        if (!name) {
            alert('Le nom est obligatoire.');
            return;
        }

        const properties = {};
        if (featureType === 'pylon') {
            properties.radius_m = parseFloat(document.getElementById('mapFeatureRadius').value) || 500;
        }
        if (featureType === 'pipeline') {
            properties.diameter_mm = parseFloat(document.getElementById('mapFeatureDiameter').value) || 400;
        }

        const typeCommerceEl = document.getElementById('mapFeatureTypeCommerce');
        const typeCommerceId = typeCommerceEl?.value ? parseInt(typeCommerceEl.value, 10) : null;
        const patchBody = { name, description, properties };
        if (typeCommerceId) {
            patchBody.type_commerce_id = typeCommerceId;
            patchBody.donnees_administratives = collectMapFeatureDonneesAdministratives() || {};
        }

        if (editId) {
            try {
                const putBody = {
                    nom: name,
                    description,
                    properties,
                    feature_type: featureType,
                };
                if (typeCommerceId) {
                    putBody.type_commerce_id = typeCommerceId;
                    putBody.donnees_administratives = collectMapFeatureDonneesAdministratives() || {};
                }
                const response = await fetch(`/api/boutiques/${editId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify(putBody),
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || 'Erreur enregistrement');
                closeSaveModal(false);
                await loadFeatures();
            } catch (e) {
                alert('Impossible d\'enregistrer : ' + e.message);
            }
            return;
        }

        if (!pendingGeometry) return;

        try {
            const postBody = {
                name,
                feature_type: featureType,
                geometry: pendingGeometry,
                properties,
                description,
            };
            if (typeCommerceId) {
                postBody.type_commerce_id = typeCommerceId;
                postBody.donnees_administratives = collectMapFeatureDonneesAdministratives() || {};
            }
            const response = await fetch('/api/map-features', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(postBody),
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Erreur enregistrement');

            if (pendingLayer && map) map.removeLayer(pendingLayer);
            pendingLayer = null;
            pendingGeometry = null;
            closeSaveModal(false);
            await loadFeatures();
        } catch (e) {
            alert('Impossible d\'enregistrer : ' + e.message);
        }
    }

    function startDraw(featureType) {
        if (!map || !TYPE_STYLES[featureType]) return;
        if (typeof window.addPoiMode !== 'undefined' && window.addPoiMode) {
            window.addPoiMode = false;
            document.getElementById('btnAddPoiMap')?.classList.remove('active');
            map.getContainer()?.classList.remove('map-click-position-mode');
        }
        stopDraw();
        currentDrawType = featureType;

        document.querySelectorAll('.map-geometry-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.geomType === featureType);
        });

        if (typeof L.Control.Draw === 'undefined') {
            alert('Outil de dessin non chargé.');
            return;
        }

        drawControl = new L.Control.Draw({
            position: 'topright',
            draw: getDrawOptions(featureType),
            edit: false,
        });
        map.addControl(drawControl);

        map.once(L.Draw.Event.CREATED, (e) => {
            const layer = e.layer;
            layer.addTo(map);
            const geometry = layerToGeometry(layer, featureType);
            removeDrawControl();
            if (onDrawComplete) {
                onDrawComplete(featureType, geometry, layer);
                return;
            }
            if (typeof window.PoiWizard !== 'undefined' && typeof window.PoiWizard.onGeometryDrawn === 'function') {
                map.removeLayer(layer);
                window.PoiWizard.onGeometryDrawn(featureType, geometry);
                return;
            }
            openSaveModal(featureType, geometry, layer);
        });
    }

    function init(mapInstance, options) {
        map = mapInstance;
        onCountsUpdate = options?.onCountsUpdate || null;
        ensureLayerGroups();

        document.getElementById('mapFeatureSaveBtn')?.addEventListener('click', savePendingFeature);
        document.getElementById('mapFeatureCancelBtn')?.addEventListener('click', () => closeSaveModal(true));
        document.querySelectorAll('.map-geom-filter').forEach(input => {
            input.addEventListener('change', () => {
                updateTypeVisibility(input.value, input.checked);
                loadFeatures();
            });
        });

        if (options?.reloadOnViewportChange) {
            map.on('moveend', scheduleViewportReload);
        }

        return loadFeatures({ useBbox: false });
    }

    return {
        init,
        loadFeatures,
        startDraw,
        stopDraw,
        startTraceFromOrigin,
        stopTrace,
        finishTrace,
        undoTracePoint,
        addTracePoint,
        getTracePointsInfo,
        removeTracePointAt,
        getTracePointCount,
        openEditModal,
        focusFeature,
        getLoadedActivityTypes,
        resolveActivityColor,
        updateTypeVisibility,
        setDrawCompleteHandler,
        TYPE_STYLES,
    };
})();
