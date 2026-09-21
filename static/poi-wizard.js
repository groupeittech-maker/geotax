/**
 * Wizard unifié de création POI — catégorie → forme → tracé → caractéristiques.
 */
window.PoiWizard = (function () {
    const STORAGE_KEY = 'geotax_poi_wizard';

    const CATEGORIES = {
        contribuable: {
            id: 'contribuable',
            label: 'Contribuable',
            subtitle: 'Assujetti à la fiscalité (taxes, QR, paiements)',
            icon: '💰',
            color: '#0d9668',
        },
        infrastructure: {
            id: 'infrastructure',
            label: 'Infrastructure',
            subtitle: 'Référentiel géographique sans fiscalité',
            icon: '🏗️',
            color: '#1565c0',
        },
    };

    const SHAPES = {
        point: {
            id: 'point',
            label: 'Point',
            subtitle: 'Commerce, école, activité…',
            icon: '📍',
            color: '#0d9668',
            drawTool: 'marker',
        },
        pylon: {
            id: 'pylon',
            label: 'Pylône',
            subtitle: 'Point + zone d\'influence',
            icon: '🗼',
            color: '#e65100',
            drawTool: 'marker',
        },
        pipeline: {
            id: 'pipeline',
            label: 'Pipeline',
            subtitle: 'Ligne, canalisation',
            icon: '🔧',
            color: '#1565c0',
            drawTool: 'polyline',
        },
        parcel: {
            id: 'parcel',
            label: 'Parcelle',
            subtitle: 'Surface cadastrale',
            icon: '📐',
            color: '#2e7d32',
            drawTool: 'polygon',
        },
        perimeter: {
            id: 'perimeter',
            label: 'Périmètre',
            subtitle: 'Zone, marché, secteur',
            icon: '⭕',
            color: '#6a1b9a',
            drawTool: 'polygon',
        },
    };

    let categoryModalEl = null;
    let modalEl = null;

    function getCategory(categoryId) {
        return CATEGORIES[categoryId] || null;
    }

    function getShape(shapeId) {
        return SHAPES[shapeId] || null;
    }

    function savePending(data, replace) {
        try {
            const merged = replace ? data : { ...(getPending() || {}), ...data };
            sessionStorage.setItem(STORAGE_KEY, JSON.stringify(merged));
        } catch (e) {
            console.warn('PoiWizard storage:', e);
        }
    }

    function getPending() {
        try {
            const raw = sessionStorage.getItem(STORAGE_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch (e) {
            return null;
        }
    }

    function clearPending() {
        sessionStorage.removeItem(STORAGE_KEY);
    }

    function ensureCategoryModal() {
        if (categoryModalEl) return categoryModalEl;

        categoryModalEl = document.createElement('div');
        categoryModalEl.id = 'poiCategoryModal';
        categoryModalEl.className = 'modal poi-shape-modal';
        categoryModalEl.innerHTML = `
            <div class="modal-overlay" data-poi-category-close></div>
            <div class="modal-content poi-shape-modal-content">
                <div class="modal-header">
                    <h2>Nouveau POI — type</h2>
                    <button type="button" class="modal-close" data-poi-category-close aria-label="Fermer">&times;</button>
                </div>
                <p class="poi-shape-intro">Choisissez d'abord s'il s'agit d'un <strong>contribuable</strong> (fiscalité) ou d'une <strong>infrastructure</strong> (référentiel).</p>
                <div class="poi-shape-grid" id="poiCategoryGrid"></div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-poi-category-close>Annuler</button>
                </div>
            </div>
        `;
        document.body.appendChild(categoryModalEl);

        categoryModalEl.querySelectorAll('[data-poi-category-close]').forEach(el => {
            el.addEventListener('click', closeCategoryPicker);
        });

        const grid = categoryModalEl.querySelector('#poiCategoryGrid');
        grid.innerHTML = Object.values(CATEGORIES).map(cat => `
            <button type="button" class="poi-shape-card" data-category="${cat.id}" style="--shape-color:${cat.color}">
                <span class="poi-shape-card-icon">${cat.icon}</span>
                <span class="poi-shape-card-label">${cat.label}</span>
                <span class="poi-shape-card-sub">${cat.subtitle}</span>
            </button>
        `).join('');

        grid.querySelectorAll('.poi-shape-card').forEach(btn => {
            btn.addEventListener('click', () => selectCategory(btn.dataset.category));
        });

        return categoryModalEl;
    }

    function ensureModal() {
        if (modalEl) return modalEl;

        modalEl = document.createElement('div');
        modalEl.id = 'poiShapeModal';
        modalEl.className = 'modal poi-shape-modal';
        modalEl.innerHTML = `
            <div class="modal-overlay" data-poi-shape-close></div>
            <div class="modal-content poi-shape-modal-content">
                <div class="modal-header">
                    <h2>Nouveau POI — choisir la forme</h2>
                    <button type="button" class="modal-close" data-poi-shape-close aria-label="Fermer">&times;</button>
                </div>
                <p class="poi-shape-intro">Catégorie : <strong id="poiShapeCategoryLabel">—</strong>. Sélectionnez la forme, puis indiquez une <strong>position de départ</strong> avant de tracer sur la carte.</p>
                <div class="poi-shape-grid" id="poiShapeGrid"></div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-poi-shape-back>← Changer le type</button>
                    <button type="button" class="btn btn-secondary" data-poi-shape-close>Annuler</button>
                </div>
            </div>
        `;
        document.body.appendChild(modalEl);

        modalEl.querySelectorAll('[data-poi-shape-close]').forEach(el => {
            el.addEventListener('click', closeShapePicker);
        });
        modalEl.querySelector('[data-poi-shape-back]')?.addEventListener('click', () => {
            closeShapePicker();
            openCategoryPicker();
        });

        const grid = modalEl.querySelector('#poiShapeGrid');
        grid.innerHTML = Object.values(SHAPES).map(shape => `
            <button type="button" class="poi-shape-card" data-shape="${shape.id}" style="--shape-color:${shape.color}">
                <span class="poi-shape-card-icon">${shape.icon}</span>
                <span class="poi-shape-card-label">${shape.label}</span>
                <span class="poi-shape-card-sub">${shape.subtitle}</span>
            </button>
        `).join('');

        grid.querySelectorAll('.poi-shape-card').forEach(btn => {
            btn.addEventListener('click', () => selectShape(btn.dataset.shape));
        });

        return modalEl;
    }

    function openCategoryPicker() {
        ensureCategoryModal();
        categoryModalEl.classList.add('modal-open');
    }

    function closeCategoryPicker() {
        if (categoryModalEl) categoryModalEl.classList.remove('modal-open');
    }

    function openShapePicker() {
        openCategoryPicker();
    }

    function closeShapePicker() {
        if (modalEl) modalEl.classList.remove('modal-open');
    }

    function selectCategory(categoryId) {
        const cat = getCategory(categoryId);
        if (!cat) return;
        closeCategoryPicker();
        const existing = getPending() || {};
        const patch = {
            categorie: categoryId,
            step: existing.shape ? 'start_position' : 'shape',
            geometry: null,
            startLat: null,
            startLng: null,
        };
        savePending(patch, !existing.shape);

        if (existing.shape && getShape(existing.shape)) {
            selectShape(existing.shape);
            return;
        }

        ensureModal();
        const label = modalEl.querySelector('#poiShapeCategoryLabel');
        if (label) label.textContent = `${cat.icon} ${cat.label}`;
        modalEl.classList.add('modal-open');
    }

    function selectShape(shapeId) {
        const pending = getPending() || {};
        const shape = getShape(shapeId);
        if (!shape) return;
        closeShapePicker();
        savePending({
            ...pending,
            shape: shapeId,
            step: 'start_position',
            geometry: null,
            startLat: null,
            startLng: null,
        });
        const onCarte = window.location.pathname.includes('/carte');
        if (onCarte && typeof window.PoiWizardOnCarte === 'function') {
            window.PoiWizardOnCarte(shapeId);
        } else {
            window.location.href = `/carte?create=${encodeURIComponent(shapeId)}`;
        }
    }

    function onGeometryDrawn(shapeId, geometry) {
        const pending = getPending() || {};
        const shape = getShape(shapeId);
        if (!shape || !geometry) return;

        savePending({
            ...pending,
            shape: shapeId,
            step: 'characteristics',
            geometry,
        });

        if (window.location.pathname.includes('/pois')) {
            if (typeof window.openPoiCharacteristicsForm === 'function') {
                window.openPoiCharacteristicsForm(getPending());
            }
        } else {
            window.location.href = '/pois?wizard=1';
        }
    }

    function formatShapeLabel(shapeId) {
        const s = getShape(shapeId);
        return s ? `${s.icon} ${s.label}` : shapeId;
    }

    function formatCategoryLabel(categoryId) {
        const c = getCategory(categoryId);
        return c ? `${c.icon} ${c.label}` : categoryId || '—';
    }

    function extractPointCoords(geometry) {
        if (!geometry) return null;
        if (geometry.type === 'Point' && geometry.coordinates) {
            return { lat: geometry.coordinates[1], lng: geometry.coordinates[0] };
        }
        return null;
    }

    return {
        CATEGORIES,
        SHAPES,
        getCategory,
        getShape,
        openShapePicker,
        openCategoryPicker,
        closeShapePicker,
        closeCategoryPicker,
        selectCategory,
        selectShape,
        onGeometryDrawn,
        getPending,
        clearPending,
        savePending,
        formatShapeLabel,
        formatCategoryLabel,
        extractPointCoords,
    };
})();
