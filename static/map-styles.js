/**
 * Styles carte GeoTax — palettes, traits, hachures, pointillés.
 */
window.GeoTaxMapStyles = (function () {
    const LINE_STYLES = {
        solid: { label: 'Trait plein', dashArray: null },
        dashed: { label: 'Tirets', dashArray: '14 10' },
        dotted: { label: 'Pointillés', dashArray: '2 10' },
        'dash-dot': { label: 'Tiret-point', dashArray: '14 8 2 8' },
        'long-dash': { label: 'Grands tirets', dashArray: '22 12' },
        'fine-dots': { label: 'Petits points', dashArray: '1 6' },
    };

    const FILL_PATTERNS = {
        solid: { label: 'Plein', fillOpacity: 0.28, type: 'solid' },
        none: { label: 'Sans remplissage', fillOpacity: 0, type: 'none' },
        'hatch-diagonal': { label: 'Hachures ↗', fillOpacity: 1, type: 'hatch', angle: 45, spacing: 10 },
        'hatch-cross': { label: 'Quadrillage', fillOpacity: 1, type: 'hatch-cross', spacing: 12 },
        dots: { label: 'Points', fillOpacity: 1, type: 'dots', spacing: 10, radius: 2.2 },
        'dots-sparse': { label: 'Points espacés', fillOpacity: 1, type: 'dots', spacing: 18, radius: 1.8 },
        'dots-dense': { label: 'Points denses', fillOpacity: 1, type: 'dots', spacing: 6, radius: 1.5 },
    };

    const PALETTES = {
        geotax: {
            label: 'GeoTax',
            colors: ['#0d9668', '#1565c0', '#e65100', '#6a1b9a', '#2e7d32', '#c62828', '#00838f', '#5d4037'],
        },
        vives: {
            label: 'Couleurs vives',
            colors: ['#e53935', '#8e24aa', '#3949ab', '#039be5', '#43a047', '#fdd835', '#fb8c00', '#6d4c41'],
        },
        pastel: {
            label: 'Pastel',
            colors: ['#81c784', '#64b5f6', '#ffb74d', '#ba68c8', '#4db6ac', '#f06292', '#aed581', '#90a4ae'],
        },
        nature: {
            label: 'Nature',
            colors: ['#2e7d32', '#558b2f', '#827717', '#00695c', '#4e342e', '#33691e', '#1b5e20', '#004d40'],
        },
        urban: {
            label: 'Urbain',
            colors: ['#37474f', '#546e7a', '#78909c', '#455a64', '#263238', '#607d8b', '#90a4ae', '#cfd8dc'],
        },
        infra: {
            label: 'Infrastructure',
            colors: ['#1565c0', '#0277bd', '#0288d1', '#0097a7', '#00838f', '#00695c', '#4527a0', '#283593'],
        },
    };

    const DEFAULT_COLOR = '#607d8b';

    function normalizeLineStyle(val) {
        return LINE_STYLES[val] ? val : 'solid';
    }

    function normalizeFillPattern(val) {
        return FILL_PATTERNS[val] ? val : 'solid';
    }

    function resolveColorFromProps(props) {
        if (props.display_color) return props.display_color;
        if (props.map_style?.color) return props.map_style.color;
        const tc = props.type_commerce;
        if (tc?.color) return tc.color;
        if (tc?.secteur?.color) return tc.secteur.color;
        return DEFAULT_COLOR;
    }

    function resolveStyleFromProps(props) {
        if (props.map_style && typeof props.map_style === 'object') {
            const ms = props.map_style;
            return {
                color: ms.color || resolveColorFromProps(props),
                lineStyle: normalizeLineStyle(ms.line_style || ms.lineStyle),
                fillPattern: normalizeFillPattern(ms.fill_pattern || ms.fillPattern),
            };
        }
        const tc = props.type_commerce;
        return {
            color: resolveColorFromProps(props),
            lineStyle: normalizeLineStyle(tc?.map_line_style),
            fillPattern: normalizeFillPattern(tc?.map_fill_pattern),
        };
    }

    function resolveStyleFromType(tc) {
        if (!tc) {
            return { color: DEFAULT_COLOR, lineStyle: 'solid', fillPattern: 'solid' };
        }
        return {
            color: tc.color || tc.secteur?.color || DEFAULT_COLOR,
            lineStyle: normalizeLineStyle(tc.map_line_style),
            fillPattern: normalizeFillPattern(tc.map_fill_pattern),
        };
    }

    function getLineDashArray(lineStyle) {
        return LINE_STYLES[lineStyle]?.dashArray ?? null;
    }

    function getFillOpacity(fillPattern, featureType) {
        const p = FILL_PATTERNS[fillPattern] || FILL_PATTERNS.solid;
        if (p.type === 'none') return 0;
        if (p.type === 'solid') {
            if (featureType === 'perimeter') return 0.12;
            if (featureType === 'parcel') return 0.28;
            if (featureType === 'pylon') return 0.15;
            return p.fillOpacity;
        }
        return 0.85;
    }

    function patternIdFor(color, patternKey) {
        const safeColor = String(color || '').replace('#', '');
        return `gtp-${patternKey}-${safeColor}`;
    }

    function ensurePatternDefsForElement(pathEl) {
        if (!pathEl) return null;
        const svg = pathEl.ownerSVGElement || pathEl.closest('svg');
        if (!svg) return null;
        let defs = svg.querySelector('defs.geotax-map-patterns');
        if (!defs) {
            defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
            defs.setAttribute('class', 'geotax-map-patterns');
            svg.insertBefore(defs, svg.firstChild);
        }
        return defs;
    }

    function buildPatternElement(color, patternKey) {
        const pattern = FILL_PATTERNS[patternKey];
        if (!pattern || pattern.type === 'solid' || pattern.type === 'none') return null;

        const spacing = pattern.spacing || 10;
        const ns = 'http://www.w3.org/2000/svg';
        const id = patternIdFor(color, patternKey);
        const pat = document.createElementNS(ns, 'pattern');
        pat.setAttribute('id', id);
        pat.setAttribute('patternUnits', 'userSpaceOnUse');
        pat.setAttribute('width', String(spacing));
        pat.setAttribute('height', String(spacing));

        const bg = document.createElementNS(ns, 'rect');
        bg.setAttribute('width', String(spacing));
        bg.setAttribute('height', String(spacing));
        bg.setAttribute('fill', color);
        bg.setAttribute('opacity', '0.12');
        pat.appendChild(bg);

        if (pattern.type === 'hatch') {
            const line = document.createElementNS(ns, 'line');
            line.setAttribute('x1', '0');
            line.setAttribute('y1', '0');
            line.setAttribute('x2', String(spacing));
            line.setAttribute('y2', String(spacing));
            line.setAttribute('stroke', color);
            line.setAttribute('stroke-width', '2');
            line.setAttribute('opacity', '0.75');
            pat.appendChild(line);
        } else if (pattern.type === 'hatch-cross') {
            [
                { x1: 0, y1: 0, x2: spacing, y2: spacing },
                { x1: spacing, y1: 0, x2: 0, y2: spacing },
            ].forEach(coords => {
                const line = document.createElementNS(ns, 'line');
                line.setAttribute('x1', String(coords.x1));
                line.setAttribute('y1', String(coords.y1));
                line.setAttribute('x2', String(coords.x2));
                line.setAttribute('y2', String(coords.y2));
                line.setAttribute('stroke', color);
                line.setAttribute('stroke-width', '1.5');
                line.setAttribute('opacity', '0.6');
                pat.appendChild(line);
            });
        } else if (pattern.type === 'dots') {
            const circle = document.createElementNS(ns, 'circle');
            circle.setAttribute('cx', String(spacing / 2));
            circle.setAttribute('cy', String(spacing / 2));
            circle.setAttribute('r', String(pattern.radius || 2));
            circle.setAttribute('fill', color);
            circle.setAttribute('opacity', '0.85');
            pat.appendChild(circle);
        }

        return { id, element: pat };
    }

    function ensurePatternOnElement(pathEl, color, patternKey) {
        const defs = ensurePatternDefsForElement(pathEl);
        if (!defs) return null;
        const id = patternIdFor(color, patternKey);
        if (!defs.querySelector(`#${id}`)) {
            const built = buildPatternElement(color, patternKey);
            if (!built) return null;
            defs.appendChild(built.element);
        }
        return id;
    }

    function applyFillPatternToElement(layer, style, featureType) {
        const fillPattern = style.fillPattern;
        const fillMeta = FILL_PATTERNS[fillPattern] || FILL_PATTERNS.solid;
        const el = layer.getElement?.();
        if (!el) return false;

        if (fillMeta.type === 'solid') {
            const opacity = getFillOpacity(fillPattern, featureType);
            layer.options.fill = true;
            layer.options.fillColor = style.color;
            layer.options.fillOpacity = opacity;
            el.setAttribute('fill', style.color);
            el.setAttribute('fill-opacity', String(opacity));
            return true;
        }

        if (fillMeta.type === 'none') {
            layer.options.fill = false;
            layer.options.fillOpacity = 0;
            el.setAttribute('fill', 'none');
            el.removeAttribute('fill-opacity');
            return true;
        }

        const patternId = ensurePatternOnElement(el, style.color, fillPattern);
        if (!patternId) return false;
        const opacity = getFillOpacity(fillPattern, featureType);
        const fillUrl = `url(#${patternId})`;
        layer.options.fill = true;
        layer.options.fillColor = fillUrl;
        layer.options.fillOpacity = opacity;
        el.setAttribute('fill', fillUrl);
        el.setAttribute('fill-opacity', String(opacity));
        return true;
    }

    function schedulePatternApply(layer, applyFn) {
        if (!layer || typeof applyFn !== 'function') return;
        requestAnimationFrame(() => {
            applyFn();
            requestAnimationFrame(applyFn);
        });
    }

    function hookLayerPatternRedraw(layer, applyPattern) {
        if (!layer || layer._geotaxPatternHooked || typeof layer._updatePath !== 'function') return;
        layer._geotaxPatternHooked = true;
        const originalUpdatePath = layer._updatePath.bind(layer);
        layer._updatePath = function geotaxUpdatePath() {
            originalUpdatePath();
            applyPattern();
        };
    }

    function applyPathStyle(layer, style, featureType) {
        if (!layer || !layer.setStyle) return;
        const dashArray = getLineDashArray(style.lineStyle);
        const fillPattern = style.fillPattern;
        const fillMeta = FILL_PATTERNS[fillPattern] || FILL_PATTERNS.solid;
        const base = {
            color: style.color,
            weight: featureType === 'pipeline' ? 5 : 2,
            opacity: 0.9,
            dashArray,
        };

        layer._geotaxFillStyle = { style, featureType };

        if (featureType === 'pipeline') {
            layer.setStyle({ ...base, fill: false, fillOpacity: 0 });
            return;
        }

        if (fillMeta.type === 'solid') {
            layer.setStyle({
                ...base,
                fill: true,
                fillColor: style.color,
                fillOpacity: getFillOpacity(fillPattern, featureType),
            });
            return;
        }

        if (fillMeta.type === 'none') {
            layer.setStyle({ ...base, fill: false, fillOpacity: 0 });
            return;
        }

        layer.setStyle({ ...base, fill: true, fillOpacity: getFillOpacity(fillPattern, featureType) });

        const applyPattern = () => {
            if (layer._geotaxApplyingFill) return;
            layer._geotaxApplyingFill = true;
            try {
                applyFillPatternToElement(layer, style, featureType);
            } finally {
                layer._geotaxApplyingFill = false;
            }
        };

        if (layer._geotaxPatternApply) {
            layer.off('add', layer._geotaxPatternApply);
        }
        layer._geotaxPatternApply = applyPattern;
        layer.on('add', applyPattern);
        hookLayerPatternRedraw(layer, applyPattern);

        if (layer._map) {
            schedulePatternApply(layer, applyPattern);
        }
    }

    function buildMarkerIconHtml(style, emoji) {
        const fillMeta = FILL_PATTERNS[style.fillPattern] || FILL_PATTERNS.solid;
        let bg = style.color;
        let bgSize = '100% 100%';
        let extraClass = '';

        if (fillMeta.type === 'hatch' || fillMeta.type === 'hatch-cross') {
            const angle = fillMeta.type === 'hatch-cross' ? '45deg, -45deg' : '45deg';
            bg = `repeating-linear-gradient(${angle}, ${style.color} 0 1px, transparent 1px 7px), ${style.color}`;
            bgSize = '10px 10px, 100% 100%';
        } else if (fillMeta.type === 'dots') {
            const sp = fillMeta.spacing || 10;
            bg = `radial-gradient(circle, ${style.color} 18%, transparent 20%), #fff`;
            bgSize = `${sp}px ${sp}px`;
        }

        const borderStyle = style.lineStyle === 'dotted' ? 'dotted'
            : style.lineStyle === 'dashed' ? 'dashed'
                : style.lineStyle === 'dash-dot' ? 'dashed' : 'solid';

        return `<div class="geotax-map-marker ${extraClass}" style="
            background:${bg};
            background-size:${bgSize};
            border:3px ${borderStyle} #fff;
            width:28px;height:28px;border-radius:50% 50% 50% 0;
            transform:rotate(-45deg);
            box-shadow:0 2px 6px rgba(0,0,0,.35);
            display:flex;align-items:center;justify-content:center;
            font-size:13px;line-height:1;
        "><span style="transform:rotate(45deg);display:block;">${emoji || '📍'}</span></div>`;
    }

    function renderPreviewSvg(style, width, height) {
        const w = width || 120;
        const h = height || 56;
        const dash = getLineDashArray(style.lineStyle);
        const dashAttr = dash ? `stroke-dasharray="${dash}"` : '';
        const fillMeta = FILL_PATTERNS[style.fillPattern] || FILL_PATTERNS.solid;
        let fill = style.color;
        let fillOpacity = getFillOpacity(style.fillPattern, 'parcel');

        if (fillMeta.type === 'hatch') {
            fill = `url(#preview-hatch-${style.fillPattern})`;
        } else if (fillMeta.type === 'hatch-cross') {
            fill = `url(#preview-hatch-cross)`;
        } else if (fillMeta.type === 'dots') {
            fill = `url(#preview-dots-${style.fillPattern})`;
        } else if (fillMeta.type === 'none') {
            fill = 'none';
            fillOpacity = 0;
        }

        const defs = fillMeta.type.startsWith('hatch') || fillMeta.type === 'dots'
            ? `<defs>
                <pattern id="preview-hatch-hatch-diagonal" width="8" height="8" patternUnits="userSpaceOnUse">
                    <line x1="0" y1="0" x2="8" y2="8" stroke="${style.color}" stroke-width="1.5" opacity="0.6"/>
                </pattern>
                <pattern id="preview-hatch-cross" width="10" height="10" patternUnits="userSpaceOnUse">
                    <line x1="0" y1="0" x2="10" y2="10" stroke="${style.color}" stroke-width="1.2" opacity="0.5"/>
                    <line x1="10" y1="0" x2="0" y2="10" stroke="${style.color}" stroke-width="1.2" opacity="0.5"/>
                </pattern>
                <pattern id="preview-dots-dots" width="10" height="10" patternUnits="userSpaceOnUse">
                    <circle cx="5" cy="5" r="2" fill="${style.color}" opacity="0.65"/>
                </pattern>
                <pattern id="preview-dots-dots-sparse" width="16" height="16" patternUnits="userSpaceOnUse">
                    <circle cx="8" cy="8" r="1.8" fill="${style.color}" opacity="0.65"/>
                </pattern>
                <pattern id="preview-dots-dots-dense" width="6" height="6" patternUnits="userSpaceOnUse">
                    <circle cx="3" cy="3" r="1.4" fill="${style.color}" opacity="0.65"/>
                </pattern>
            </defs>`
            : '';

        const fillUrl = fillMeta.type === 'hatch' ? 'url(#preview-hatch-hatch-diagonal)'
            : fillMeta.type === 'hatch-cross' ? 'url(#preview-hatch-cross)'
                : fillMeta.type === 'dots' ? `url(#preview-dots-${style.fillPattern})`
                    : style.color;

        return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg">
            ${defs}
            <rect x="4" y="8" width="${w - 8}" height="${h - 16}" rx="4"
                fill="${fillMeta.type === 'solid' || fillMeta.type === 'none' ? fill : fillUrl}"
                fill-opacity="${fillOpacity}" stroke="${style.color}" stroke-width="2.5" ${dashAttr}/>
            <line x1="8" y1="${h - 6}" x2="${w - 8}" y2="${h - 6}" stroke="${style.color}" stroke-width="2.5" ${dashAttr}/>
        </svg>`;
    }

    return {
        LINE_STYLES,
        FILL_PATTERNS,
        PALETTES,
        DEFAULT_COLOR,
        normalizeLineStyle,
        normalizeFillPattern,
        resolveStyleFromProps,
        resolveStyleFromType,
        resolveColorFromProps,
        getLineDashArray,
        getFillOpacity,
        applyPathStyle,
        buildMarkerIconHtml,
        renderPreviewSvg,
        ensurePatternOnElement,
    };
})();
