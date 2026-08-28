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
);

echo wp_json_encode( $out, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE );
