<?php
/**
 * Write serialized block markup into a post, safely.
 *
 *   wp eval-file tools/apply-post.php <post_id> <content-file>
 *   wp eval-file tools/apply-post.php new <content-file> "Title" [post_type] [status]
 *
 * Why not `wp post update` with a file:
 *   - kses. WP-CLI runs with no user; no user means no `unfiltered_html`, and
 *     kses_init() has hooked the filters. Your markup gets rewritten on the way
 *     in - attrs JSON escapes eaten, tags stripped - with no error. This script
 *     removes the kses filters for the write, exactly like an admin saving.
 *   - slashing. wp_update_post() unslashes. Content containing backslashes
 *     (-- escapes in attrs JSON) must be wp_slash()ed first or the
 *     stored markup differs from the file. Silently.
 *
 * After the write it verifies round-trip (stored === file), reports the block
 * count parse_blocks() sees, and purges the page caches (Breeze + object
 * cache) so what you verify next is what visitors get.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit( 1 );
}

if ( count( $args ) < 2 ) {
	WP_CLI::error( 'usage: wp eval-file tools/apply-post.php <post_id|new> <content-file> ["Title"] [post_type] [status]' );
}

list( $target, $file ) = $args;
$content = file_get_contents( $file );
if ( false === $content ) {
	WP_CLI::error( "cannot read $file" );
}
$content = rtrim( $content, "\n" );

$parsed  = parse_blocks( $content );
$count   = 0;
$walk    = function ( $blocks ) use ( &$walk, &$count ) {
	foreach ( $blocks as $b ) {
		if ( null !== $b['blockName'] ) {
			$count++;
			$walk( $b['innerBlocks'] );
		}
	}
};
$walk( $parsed );
if ( 0 === $count ) {
	WP_CLI::error( 'parse_blocks() found no blocks in the file - refusing to write' );
}

kses_remove_filters();

// Per-block custom CSS (style.css, WP 7.0+) is stripped on save by a SEPARATE
// filter when the acting user lacks `edit_css` - and WP-CLI has no user at all.
// kses_remove_filters() does not touch it; remove it explicitly or the write
// silently loses every style.css in the file.
if ( function_exists( 'wp_custom_css_remove_filters' ) ) {
	wp_custom_css_remove_filters();
}

if ( 'new' === $target ) {
	$post_id = wp_insert_post( array(
		'post_title'   => isset( $args[2] ) ? $args[2] : 'Untitled',
		'post_type'    => isset( $args[3] ) ? $args[3] : 'page',
		'post_status'  => isset( $args[4] ) ? $args[4] : 'publish',
		'post_content' => wp_slash( $content ),
	), true );
	if ( is_wp_error( $post_id ) ) {
		WP_CLI::error( $post_id->get_error_message() );
	}
} else {
	$post_id = (int) $target;
	$before  = get_post( $post_id );
	if ( ! $before ) {
		WP_CLI::error( "no post $post_id" );
	}
	$r = wp_update_post( array(
		'ID'           => $post_id,
		'post_content' => wp_slash( $content ),
	), true );
	if ( is_wp_error( $r ) ) {
		WP_CLI::error( $r->get_error_message() );
	}
}

// ---- round-trip check: is what got STORED what the file says? -------------
clean_post_cache( $post_id );
$stored = get_post( $post_id )->post_content;
if ( $stored !== $content ) {
	$n = strspn( $stored ^ $content, "\0" );
	WP_CLI::warning( sprintf(
		'stored content differs from the file at byte %d: file %s / stored %s',
		$n, var_export( substr( $content, $n, 40 ), true ), var_export( substr( $stored, $n, 40 ), true )
	) );
} else {
	WP_CLI::log( 'round-trip: stored content is byte-identical to the file' );
}

// ---- purge what sits between the database and the visitor -----------------
if ( function_exists( 'wp_cache_flush' ) ) {
	wp_cache_flush();
}
if ( class_exists( 'Breeze_PurgeCache' ) ) {
	do_action( 'breeze_clear_all_cache' );
	WP_CLI::log( 'Breeze cache purged' );
}
if ( function_exists( 'wp_cache_clean_cache' ) ) {
	global $file_prefix;
	wp_cache_clean_cache( $file_prefix, true );
}

WP_CLI::success( sprintf(
	'post %d written: %d blocks. view: %s  edit: %s',
	$post_id, $count, get_permalink( $post_id ),
	admin_url( 'post.php?post=' . $post_id . '&action=edit' )
) );
