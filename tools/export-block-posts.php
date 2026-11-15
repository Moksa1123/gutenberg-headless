<?php
/**
 * export-block-posts.php - dump every post that contains block markup, read-only.
 *
 *   wp eval-file tools/export-block-posts.php > block-posts.json
 *   python tools/roundtrip-check.py block-posts.json --out data/roundtrip-verification.csv
 *
 * Feeds roundtrip-check.py, which round-trips each post_content through
 * blockmark.py and records where the stored bytes differ from the canonical form.
 * Writes nothing to the site.
 */

$ids = get_posts( array(
	'post_type'   => 'any',
	'post_status' => array( 'publish', 'draft', 'private', 'pending', 'future' ),
	'numberposts' => -1,
	'fields'      => 'ids',
) );

$posts = array();
foreach ( $ids as $id ) {
	$content = get_post_field( 'post_content', $id );
	if ( false === strpos( $content, '<!-- wp:' ) ) {
		continue;
	}
	$posts[] = array(
		'id'      => $id,
		'type'    => get_post_type( $id ),
		'content' => $content,
	);
}

$theme = wp_get_theme();
echo wp_json_encode( array(
	'site'        => home_url(),
	'wp'          => get_bloginfo( 'version' ),
	'woocommerce' => defined( 'WC_VERSION' ) ? WC_VERSION : null,
	'theme'       => $theme->get( 'Name' ) . ' ' . $theme->get( 'Version' ),
	'exported_at' => gmdate( 'Y-m-d' ),
	'posts'       => $posts,
) );
