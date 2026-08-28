// Extract everything the block editor knows that the SERVER does not.
//
// Run in the block editor of the target site (any post), as an admin:
//   the console, or browser automation, or paste into the browser devtools.
//
// WHY A SECOND EXTRACTOR EXISTS
// extract-block-schema.php reads WP_Block_Type_Registry, which is the whole
// truth for attributes and supports and nothing like it for the rest. Measured
// on a real site: the PHP registry reports 3 variations; the editor has 152.
// It reports no transforms; the editor has 428. It reports no deprecations;
// the editor has 190 - and a deprecation is exactly the thing that lets
// WordPress accept your markup today and rewrite it on the next manual save.
//
// It also settles canonicalization, which was folklore in this repo until it
// was measured: the ORDER of classes, of inline CSS declarations, and of the
// attributes inside the tag are all decided by each block's save(), they
// differ per block, and getting them wrong costs byte-identity (the editor
// reserializes your whole page on its next save).
//
// OUTPUT
// One JSON object, meant for data/editor-surface.json and queried through
// gb.py - never read whole.
(async () => {
  const B = window.wp && wp.blocks;
  if (!B) return JSON.stringify({ error: 'wp.blocks not available - open a block editor screen' });

  // A style object touching every group the style engine can emit, so the
  // save() probe below reveals the FULL declaration order rather than the
  // subset a given page happens to use.
  const PROBE_STYLE = {
    border: { color: '#333333', radius: '9px', style: 'solid', width: '1px' },
    color: { background: '#111111', text: '#222222' },
    // All four, because a property the probe never sets has no position in the
    // canonical order and sorts to the end - `width` did exactly that, and the
    // converted page put it after padding where save() puts it before.
    dimensions: { minHeight: '10px', height: '20px', width: '100px', aspectRatio: '16/9' },
    spacing: {
      margin: { top: '1px', right: '2px', bottom: '3px', left: '4px' },
      padding: { top: '5px', right: '6px', bottom: '7px', left: '8px' }
    },
    typography: {
      fontSize: '16px', fontFamily: 'PF', fontStyle: 'italic', fontWeight: '600',
      letterSpacing: '1px', lineHeight: '2', textDecoration: 'underline',
      textTransform: 'uppercase',
      // Produces has-text-align-*, which every aligned paragraph carries.
      // It is NOT the `align` attribute (that yields alignfull) and not
      // `textAlign` either - both were probed and produced no class at all,
      // so the class had no recorded position and sorted to the end.
      textAlign: 'left'
    },
    shadow: '0 0 1px #000'
  };
  const PROBE_CLASS = 'ZZPROBECLS';

  // A block's class order is not always a fixed list: core/separator emits
  // `has-text-color has-alpha-channel-opacity` when a background is also set
  // and `has-alpha-channel-opacity has-text-color` when it is not. Probing one
  // attribute combination and treating the result as THE order produces false
  // reports on markup that is provably canonical. So every block is probed
  // several ways, and only orderings that hold in ALL of them are a rule.
  //
  // Every variant sets `align` and per-block custom CSS as well, because a
  // canonical order is only useful if it covers the classes a page actually
  // carries: `alignfull` and `has-custom-css` are two of them, and a token the
  // probe never saw has no defined position at all.
  const V_STYLE = (extra) => ({ css: 'color:red', ...extra });
  const VARIANTS = [
    { name: 'full', style: V_STYLE(PROBE_STYLE), fontFamily: 'pf', fontSize: 'large' },
    { name: 'colors', style: V_STYLE({ color: PROBE_STYLE.color }) },
    { name: 'text-only', style: V_STYLE({ color: { text: '#222222' } }) },
    { name: 'type', style: V_STYLE({ typography: PROBE_STYLE.typography }) },
    { name: 'border', style: V_STYLE({ border: PROBE_STYLE.border }) },
    { name: 'spacing', style: V_STYLE({ spacing: PROBE_STYLE.spacing }) },
    // Preset slugs produce has-{slug}-color / has-{slug}-background-color,
    // which sit in a different place from the literal has-text-color pair.
    { name: 'presets', style: V_STYLE({}), backgroundColor: 'palette-color-6',
      textColor: 'palette-color-1', fontFamily: 'pf', fontSize: 'large' },
    // Text alignment WITHOUT anything else, so its class is constrained
    // against the wrapper classes rather than only against typography.
    { name: 'align', style: V_STYLE({ typography: { textAlign: 'left' } }) },
  ];

  // Fill the attributes a block needs before save() will produce anything -
  // a heading with no content saves an empty string and tells us nothing.
  const fillContent = (type, attrs) => {
    for (const [k, def] of Object.entries(type.attributes || {})) {
      if (attrs[k] !== undefined && attrs[k] !== '') continue;
      const t = def.type;
      if (def.source === 'rich-text' || t === 'rich-text') attrs[k] = 'PROBE';
      else if (def.role === 'content' && t === 'string') attrs[k] = 'PROBE';
    }
    return attrs;
  };

  const tagsOf = (html) => [...html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*)>/g)]
    .map(m => ({
      tag: m[1],
      // Attribute NAMES in source order. Byte-identity depends on this:
      // core/button emits class before href, and writing href first is valid,
      // renders the same, and still gets rewritten on the next save.
      attrs: [...m[2].matchAll(/\s([a-zA-Z-]+)=/g)].map(a => a[1]),
      classes: (m[2].match(/class="([^"]*)"/) || [, ''])[1].split(/\s+/).filter(Boolean),
      css: (m[2].match(/style="([^"]*)"/) || [, ''])[1]
        .split(';').filter(Boolean).map(d => d.split(':')[0].trim())
    }));

  const out = { extracted_at: new Date().toISOString(), url: location.origin, blocks: {} };
  try { out.wp_version = wp.data.select('core').getEntityRecord ? undefined : undefined; } catch (e) { /* noop */ }

  for (const type of B.getBlockTypes()) {
    const rec = { name: type.name };

    // --- variations: almost all of them are registered in JS ---
    const vars = B.getBlockVariations(type.name) || [];
    if (vars.length) {
      rec.variations = vars.map(v => ({
        name: v.name, title: v.title,
        isDefault: !!v.isDefault,
        scope: v.scope || null,
        // The attributes are what a variation MEANS - they are the difference
        // between core/group and its Row/Stack/Grid faces.
        attributes: v.attributes || {},
        innerBlocks: Array.isArray(v.innerBlocks)
          ? v.innerBlocks.map(ib => (Array.isArray(ib) ? ib[0] : ib && ib.name) || null) : null
      }));
    }

    // --- transforms: what this block can become, and what becomes it ---
    const tr = type.transforms || {};
    const side = (list) => (list || []).map(t => ({
      type: t.type,
      blocks: t.blocks || null,
      tag: t.tag || null,
      priority: t.priority === undefined ? null : t.priority,
      isMatch: !!t.isMatch, isMultiBlock: !!t.isMultiBlock
    }));
    if ((tr.from || []).length || (tr.to || []).length) {
      rec.transforms = { from: side(tr.from), to: side(tr.to) };
    }

    // --- deprecations: the reason "valid" is not the same as "stable" ---
    const dep = type.deprecated || [];
    if (dep.length) {
      rec.deprecated = dep.map((d, i) => ({
        index: i,
        // What the old form differed in. `migrate` means the attributes
        // themselves get rewritten, which is the destructive case.
        hasMigrate: typeof d.migrate === 'function',
        hasIsEligible: typeof d.isEligible === 'function',
        changedAttributes: Object.keys(d.attributes || {}),
        changedSupports: Object.keys(d.supports || {})
      }));
    }

    // --- attributes that block bindings / pattern overrides can drive ---
    const content = Object.entries(type.attributes || {})
      .filter(([, d]) => d && d.role === 'content').map(([k]) => k);
    if (content.length) rec.contentAttributes = content;

    // --- what save() actually writes, per block ---
    // This is the canonical form. Everything else in this repo about class
    // order and CSS order was hand-derived from four blocks; this reads it
    // from all of them.
    try {
      const variants = [];
      let shape = null;
      for (const v of VARIANTS) {
        const attrs = fillContent(type, {
          ...B.getBlockAttributes(type, ''), className: PROBE_CLASS,
          align: v.align || 'full', textAlign: v.textAlign,
          style: v.style, fontFamily: v.fontFamily, fontSize: v.fontSize,
          backgroundColor: v.backgroundColor, textColor: v.textColor
        });
        let html;
        try { html = B.getSaveContent(type, attrs, []); } catch (e) { continue; }
        if (!html || typeof html !== 'string' || !html.trim()) continue;
        const els = tagsOf(html);
        if (!els.length) continue;
        variants.push({ classes: els[0].classes, css: els[0].css });
        if (v.name === 'full') {
          shape = {
            elements: els.slice(0, 3),
            // Which element the block's `className` lands on - 0 is the
            // wrapper. core/button puts it on the wrapper and builds the <a>
            // itself, so a class written onto the <a> makes the block invalid.
            classNameOn: els.findIndex(e => e.classes.includes(PROBE_CLASS))
          };
        }
      }
      if (shape) {
        // The variants themselves ship; the consumer intersects them into the
        // orderings that always hold. Keeping them raw means a later question
        // ("is this pair stable?") can be answered without re-probing a site.
        shape.variants = variants;
        rec.save = shape;
      } else if (!variants.length) {
        rec.save = { dynamic: true };     // renders server-side, saves nothing
      } else {
        rec.save = { variants };
      }
    } catch (e) {
      rec.save = { error: String(e && e.message || e).slice(0, 80) };
    }

    // Only keep blocks that told us something the server did not.
    if (rec.variations || rec.transforms || rec.deprecated || rec.contentAttributes || rec.save) {
      out.blocks[type.name] = rec;
    }
  }

  out.block_count = Object.keys(out.blocks).length;
  out.totals = Object.values(out.blocks).reduce((a, b) => ({
    variations: a.variations + (b.variations ? b.variations.length : 0),
    transforms: a.transforms + (b.transforms ? b.transforms.from.length + b.transforms.to.length : 0),
    deprecated: a.deprecated + (b.deprecated ? b.deprecated.length : 0)
  }), { variations: 0, transforms: 0, deprecated: 0 });

  return JSON.stringify(out);
})()
