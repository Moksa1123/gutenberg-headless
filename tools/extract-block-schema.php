<?php
/**
 * Dump the full block-editor surface of a live WordPress install.
 *
 * Usage:  wp eval-file tools/extract-block-schema.php > dump.json
 *
 * Everything the block editor knows server-side, in one JSON document:
 *   - every registered block type: attributes, supports, styles, variations,
 *     parent/ancestor constraints, context, whether it is dynamic
 *   - the merged theme.json settings (global + theme + user): the preset
 *     palettes, font sizes, spacing scale, layout sizes - per-block overrides too
 *   - registered block patterns and pattern categories (names, not content)
 *   - registered block style variations
 *   - the environment: WP version, theme, whether it is a block theme,
 *     active plugins (the block surface is a property of the SITE)
 *
 * What this CANNOT see (and says so): the JS-only editor layer - client-side
 * registerBlockType calls, block deprecations, the save() functions. Those live
 * in the browser. Serialized markup correctness is verified by rendering, not
 * by reading source.
 */

if ( ! defined( 'ABSPATH' ) ) {
	fwrite( STDERR, "Run via: wp eval-file tools/extract-block-schema.php\n" );
	exit( 1 );
}

/**
 * Optional: describe the site AS IF another theme were active.
 *
 *   wp eval-file tools/extract-block-schema.php twentytwentyfive
 *
 * Nothing is written and nothing changes for a visitor - the theme is swapped
 * by filter inside this one CLI process, the theme.json caches are dropped, and
 * the process exits. It exists because the block surface is a property of the
 * THEME as much as of the site: presets, layout sizes, the whole Site Editor
 * (templates, template parts, style variations) all appear or vanish with it.
 * Planning a move to a block theme should not require performing it first.
 */
if ( ! empty( $args[0] ) ) {
	$as_theme = preg_replace( '/[^a-z0-9_-]/i', '', (string) $args[0] );
	$dir      = WP_CONTENT_DIR . '/themes/' . $as_theme;
	if ( ! is_dir( $dir ) ) {
		fwrite( STDERR, "theme '$as_theme' is not installed\n" );
		exit( 1 );
	}
	foreach ( array( 'stylesheet', 'template' ) as $f ) {
		add_filter( $f, function () use ( $as_theme ) { return $as_theme; } );
	}
	foreach ( array( 'stylesheet_directory', 'template_directory' ) as $f ) {
		add_filter( $f, function () use ( $dir ) { return $dir; } );
	}
	if ( method_exists( 'WP_Theme_JSON_Resolver', 'clean_cached_data' ) ) {
		WP_Theme_JSON_Resolver::clean_cached_data();
	}
	wp_clean_themes_cache();
	// What this CANNOT do, measured by diffing the two extractions: it does not
	// re-run the real theme's PHP. `add_theme_support()` calls fired at
	// after_setup_theme long before these filters, so `theme_supports` below
	// still describes the ACTIVE theme. Everything theme.json declares -
	// presets, layout sizes, viewport, templates, parts, style variations -
	// is read fresh and is correct.
	$pretending = array(
		'theme'  => $as_theme,
		'faithful_for' => 'theme.json settings and styles, templates, template parts, '
						. 'style variations, customTemplates, templateParts',
		'stale_for'    => 'theme_supports (registered by the ACTIVE theme at after_setup_theme, '
						. 'before this process could intervene)',
	);
}

$registry = WP_Block_Type_Registry::get_instance();
$blocks   = array();

foreach ( $registry->get_all_registered() as $name => $bt ) {
	// Variations may be lazy (registered via callback since WP 6.5).
	$variations = array();
	foreach ( (array) $bt->variations as $v ) {
		$variations[] = array(
			'name'       => isset( $v['name'] ) ? $v['name'] : '',
			'title'      => isset( $v['title'] ) ? $v['title'] : '',
			'isDefault'  => ! empty( $v['isDefault'] ),
			'attributes' => isset( $v['attributes'] ) ? $v['attributes'] : (object) array(),
		);
	}

	$styles = array();
	foreach ( (array) $bt->styles as $s ) {
		$styles[] = array(
			'name'      => isset( $s['name'] ) ? $s['name'] : '',
			'label'     => isset( $s['label'] ) ? $s['label'] : '',
			'isDefault' => ! empty( $s['is_default'] ) || ! empty( $s['isDefault'] ),
		);
	}

	$blocks[ $name ] = array(
		'name'             => $name,
		'title'            => (string) $bt->title,
		'description'      => (string) $bt->description,
		'category'         => $bt->category,
		'api_version'      => $bt->api_version,
		'parent'           => $bt->parent,
		'ancestor'         => $bt->ancestor,
		'allowed_blocks'   => isset( $bt->allowed_blocks ) ? $bt->allowed_blocks : null,
		'keywords'         => $bt->keywords,
		'textdomain'       => $bt->textdomain,
		'attributes'       => is_array( $bt->attributes ) ? $bt->attributes : array(),
		'supports'         => is_array( $bt->supports ) ? $bt->supports : array(),
		'styles'           => $styles,
		'variations'       => $variations,
		'uses_context'     => $bt->uses_context,
		'provides_context' => $bt->provides_context,
		'is_dynamic'       => $bt->is_dynamic(),
		// `selectors` says WHICH element inside the block each style group is
		// applied to. Without it the style engine's output is guesswork for
		// any block that is not a single element - 18 blocks here.
		'selectors'        => ( isset( $bt->selectors ) && $bt->selectors ) ? $bt->selectors : null,
		// Hooked blocks insert themselves next to other blocks at render time,
		// so a page can contain markup nobody wrote.
		'block_hooks'      => ( isset( $bt->block_hooks ) && $bt->block_hooks ) ? $bt->block_hooks : null,
		'has_example'      => ! empty( $bt->example ),
		// A variation_callback means the PHP `variations` array is empty until
		// it runs - reading the property alone under-reports.
		'variation_callback' => isset( $bt->variation_callback ) && $bt->variation_callback ? true : false,
	);
}

// ---- theme.json: the merged settings the editor actually uses -------------
$global_settings = function_exists( 'wp_get_global_settings' ) ? wp_get_global_settings() : array();
$global_styles   = function_exists( 'wp_get_global_styles' ) ? wp_get_global_styles() : array();

// ---- patterns (names only - content can be huge) --------------------------
$patterns = array();
if ( class_exists( 'WP_Block_Patterns_Registry' ) ) {
	foreach ( WP_Block_Patterns_Registry::get_instance()->get_all_registered() as $p ) {
		$patterns[] = array(
			'name'       => $p['name'],
			'title'      => isset( $p['title'] ) ? $p['title'] : '',
			'categories' => isset( $p['categories'] ) ? $p['categories'] : array(),
			'inserter'   => ! isset( $p['inserter'] ) || $p['inserter'],
			'source'     => isset( $p['source'] ) ? $p['source'] : '',
			'bytes'      => isset( $p['content'] ) ? strlen( $p['content'] ) : 0,
		);
	}
}

// ---- block bindings sources -------------------------------------------------
// What a `metadata.bindings` entry is allowed to name. core/pattern-overrides
// is the one that turns a synced pattern into a template with editable slots;
// acf/field and core/post-meta bind a block to stored data. Nothing about any
// of this is visible in the block registry.
$binding_sources = array();
if ( function_exists( 'get_all_registered_block_bindings_sources' ) ) {
	foreach ( get_all_registered_block_bindings_sources() as $name => $src ) {
		$binding_sources[] = array(
			'name'             => $name,
			'label'            => isset( $src->label ) ? (string) $src->label : '',
			'uses_context'     => isset( $src->uses_context ) ? $src->uses_context : array(),
			'has_get_value'    => isset( $src->get_value_callback ) && $src->get_value_callback ? true : false,
		);
	}
}

// ---- templates -------------------------------------------------------------
// Two unrelated things both called "template", and which of them exists is a
// property of the THEME: wp_template/wp_template_part are block-theme only,
// while a post type's own `template` works on any theme.
$templates = array(
	'is_block_theme'   => function_exists( 'wp_is_block_theme' ) ? wp_is_block_theme() : false,
	'wp_template'      => 0,
	'wp_template_part' => 0,
	'post_type_templates' => array(),
	'synced_patterns'  => 0,
);
foreach ( array( 'wp_template', 'wp_template_part' ) as $pt ) {
	$c = wp_count_posts( $pt );
	$templates[ $pt ] = $c ? (int) array_sum( (array) $c ) : 0;
}
$wpb = wp_count_posts( 'wp_block' );
$templates['synced_patterns'] = $wpb ? (int) array_sum( (array) $wpb ) : 0;
foreach ( get_post_types( array(), 'objects' ) as $pt ) {
	if ( ! empty( $pt->template ) ) {
		$templates['post_type_templates'][] = array(
			'post_type'     => $pt->name,
			'template_lock' => isset( $pt->template_lock ) ? $pt->template_lock : false,
			'blocks'        => wp_list_pluck( $pt->template, 0 ),
		);
	}
}

// ---- the Site Editor surface ------------------------------------------------
// All of this is EMPTY on a classic theme and is the whole authoring surface on
// a block one, so a schema that omits it describes only half the WordPresses
// there are. The template types and part areas come from core and exist either
// way; everything else is the active theme's.
$templates['default_template_types'] = function_exists( 'get_default_block_template_types' )
	? array_keys( get_default_block_template_types() ) : array();
$templates['template_part_areas'] = function_exists( 'get_allowed_block_template_part_areas' )
	? wp_list_pluck( get_allowed_block_template_part_areas(), 'area' ) : array();

$templates['resolved'] = array( 'wp_template' => array(), 'wp_template_part' => array() );
if ( function_exists( 'get_block_templates' ) ) {
	foreach ( array( 'wp_template', 'wp_template_part' ) as $pt ) {
		foreach ( get_block_templates( array(), $pt ) as $t ) {
			$templates['resolved'][ $pt ][] = array(
				'slug'   => $t->slug,
				'title'  => $t->title,
				// `theme` means it comes from a file; `custom` means a user
				// edited it and it now lives in the database, overriding the file.
				'source' => $t->source,
				'area'   => isset( $t->area ) ? $t->area : null,
				'bytes'  => strlen( (string) $t->content ),
			);
		}
	}
}

// theme.json's own declarations - the parts a theme offers and the templates it
// lets an author pick per post.
$theme_json_raw = array();
if ( class_exists( 'WP_Theme_JSON_Resolver' ) ) {
	$theme_data = WP_Theme_JSON_Resolver::get_theme_data();
	$raw = $theme_data ? $theme_data->get_raw_data() : array();
	foreach ( array( 'templateParts', 'customTemplates' ) as $k ) {
		if ( ! empty( $raw[ $k ] ) ) {
			$theme_json_raw[ $k ] = $raw[ $k ];
		}
	}
	// Alternate palettes a block theme ships in styles/*.json.
	if ( method_exists( 'WP_Theme_JSON_Resolver', 'get_style_variations' ) ) {
		$vars = WP_Theme_JSON_Resolver::get_style_variations();
		$theme_json_raw['style_variations'] = array_values( array_filter( array_map(
			function ( $v ) { return isset( $v['title'] ) ? $v['title'] : null; },
			(array) $vars
		) ) );
	}
	// The USER layer of the cascade: one wp_global_styles post per theme,
	// highest priority of all. It exists even on a classic theme, usually empty.
	$user = WP_Theme_JSON_Resolver::get_user_data();
	$user_raw = $user ? $user->get_raw_data() : array();
	$theme_json_raw['user_overrides'] = array_values( array_diff( array_keys( $user_raw ), array( 'version' ) ) );
}
$templates['theme_json'] = $theme_json_raw;

// ---- what the EDITOR is configured to allow ---------------------------------
// get_block_editor_settings() is where "can a human change this here" is
// decided. It does not constrain the markup - a page can carry an inline
// line-height on a theme with custom-line-height off, and it renders - but it
// decides whether anyone can edit that value afterwards, which is the
// difference between a page and a page someone can maintain.
$editor_settings = array();
if ( function_exists( 'get_block_editor_settings' ) && class_exists( 'WP_Block_Editor_Context' ) ) {
	$posts = get_posts( array( 'numberposts' => 1, 'post_type' => 'page' ) );
	$ctx   = new WP_Block_Editor_Context( $posts ? array( 'post' => $posts[0] ) : array() );
	$all   = get_block_editor_settings( array(), $ctx );
	foreach ( array(
		'alignWide', 'allowedBlockTypes', 'disableCustomColors', 'disableCustomFontSizes',
		'disableCustomGradients', 'disableCustomSpacingSizes', 'disableLayoutStyles',
		'enableCustomLineHeight', 'enableCustomSpacing', 'enableCustomUnits',
		'imageDefaultSize', 'imageEditing', 'maxUploadFileSize', 'isRTL',
		'canEditCSS', 'canUpdateBlockBindings', '__unstableIsBlockBasedTheme',
		'__experimentalBlockBindingsSupportedAttributes',
	) as $k ) {
		if ( array_key_exists( $k, $all ) ) {
			// allowedBlockTypes is `true` (everything) or a list; keep the shape.
			$editor_settings[ $k ] = $all[ $k ];
		}
	}
	$editor_settings['imageSizes'] = isset( $all['imageSizes'] )
		? wp_list_pluck( $all['imageSizes'], 'slug' ) : array();
	$editor_settings['editor_style_sheets'] = isset( $all['styles'] ) ? count( $all['styles'] ) : 0;
}

// ---- theme_supports: the classic-theme source of truth ----------------------
// A classic theme declares its editor surface here, not in theme.json. Blocksy
// is one, so this is where align-wide and the colour palette actually come
// from - reading theme.json alone describes a file the theme may not have.
$theme_supports = array();
foreach ( array(
	'align-wide', 'editor-styles', 'dark-editor-style', 'responsive-embeds',
	'custom-line-height', 'custom-units', 'custom-spacing', 'appearance-tools',
	'wp-block-styles', 'disable-custom-colors', 'disable-custom-font-sizes',
	'disable-custom-gradients', 'editor-color-palette', 'editor-font-sizes',
	'editor-gradient-presets', 'post-thumbnails', 'html5',
) as $f ) {
	$theme_supports[ $f ] = current_theme_supports( $f );
}

// ---- what the theme already styles, per block -------------------------------
// theme.json `styles.blocks.*` is the reason a block can look styled before you
// write anything - and the reason a value you DID write can look ignored.
$block_styles_defaults = array();
foreach ( ( isset( $global_styles['blocks'] ) ? $global_styles['blocks'] : array() ) as $name => $decl ) {
	$block_styles_defaults[ $name ] = array_keys( (array) $decl );
}
$block_settings = array();
foreach ( ( isset( $global_settings['blocks'] ) ? $global_settings['blocks'] : array() ) as $name => $decl ) {
	$block_settings[ $name ] = $decl;
}

// ---- the breakpoints each block hardcodes in its own stylesheet -------------
// theme.json's `settings.viewport` decides what `style["@mobile"]` compiles to,
// and it decides NOTHING about a block that ships its own media query. Measured
// here rather than assumed, because the values disagree: core/columns stacks at
// 781px and core/media-text at 600px, both through an attribute called
// `isStackedOnMobile`.
$block_breakpoints = array();
$css_dir = ABSPATH . WPINC . '/blocks';
if ( is_dir( $css_dir ) ) {
	foreach ( glob( $css_dir . '/*/style.min.css' ) as $file ) {
		$css = file_get_contents( $file );
		if ( ! $css || false === strpos( $css, '@media' ) ) {
			continue;
		}
		preg_match_all( '/@media\s*\(([^)]*(?:width)[^)]*)\)/i', $css, $m );
		if ( empty( $m[1] ) ) {
			continue;
		}
		$slug = basename( dirname( $file ) );
		$block_breakpoints[ 'core/' . $slug ] = array_values( array_unique( array_map( 'trim', $m[1] ) ) );
	}
}

$pattern_categories = array();
if ( class_exists( 'WP_Block_Pattern_Categories_Registry' ) ) {
	foreach ( WP_Block_Pattern_Categories_Registry::get_instance()->get_all_registered() as $c ) {
		$pattern_categories[] = $c['name'];
	}
}

// ---- block categories ------------------------------------------------------
$categories = array();
if ( function_exists( 'get_block_categories' ) ) {
	$post = get_posts( array( 'numberposts' => 1, 'post_type' => 'page' ) );
	$cats = $post ? get_block_categories( $post[0] ) : get_default_block_categories();
	foreach ( $cats as $c ) {
		$categories[] = array( 'slug' => $c['slug'], 'title' => $c['title'] );
	}
}

// ---- environment -----------------------------------------------------------
$theme   = wp_get_theme();
$plugins = array();
foreach ( (array) get_option( 'active_plugins' ) as $p ) {
	$plugins[] = dirname( $p ) !== '.' ? dirname( $p ) : $p;
}

$out = array(
	'extracted_at'       => gmdate( 'c' ),
	'wp_version'         => get_bloginfo( 'version' ),
	'site_url'           => get_site_url(),
	'theme'              => array(
		'name'           => $theme->get( 'Name' ),
		'stylesheet'     => $theme->get_stylesheet(),
		'version'        => $theme->get( 'Version' ),
		'is_block_theme' => function_exists( 'wp_is_block_theme' ) ? wp_is_block_theme() : false,
	),
	'active_plugins'     => $plugins,
	'block_count'        => count( $blocks ),
	'blocks'             => $blocks,
	'block_categories'   => $categories,
	'global_settings'    => $global_settings,
	'global_styles'      => $global_styles,
	'patterns'           => $patterns,
	'pattern_categories' => $pattern_categories,
	'binding_sources'    => $binding_sources,
	'templates'          => $templates,
	'editor_settings'    => $editor_settings,
	'theme_supports'     => $theme_supports,
	'block_style_defaults' => $block_styles_defaults,
	'block_settings'     => $block_settings,
	'block_breakpoints'  => $block_breakpoints,
	'pretending'         => isset( $pretending ) ? $pretending : null,
);

echo wp_json_encode( $out, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE );
