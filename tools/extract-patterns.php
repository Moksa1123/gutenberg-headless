<?php
/**
 * Dump every registered block pattern's CONTENT.
 *
 *   wp eval-file tools/extract-patterns.php > data/patterns.json
 *
 * The main schema records pattern names and byte counts only, because the
 * content is bulky and no query needs it. It is worth having separately for one
 * reason: a pattern's content is serialized block markup written BY CORE (and
 * by the active plugins and theme), which makes it the largest corpus of
 * canonical markup available for the target site.
 *
 * Use it as a self-test. Running validate-post.py over this corpus asks whether
 * the rules in that validator agree with what WordPress itself ships. A failure
 * is a finding either way round: the validator is wrong about the format, or a
 * shipped pattern really is inconsistent with the block it uses.
 */

if ( ! class_exists( 'WP_Block_Patterns_Registry' ) ) {
	fwrite( STDERR, "WP_Block_Patterns_Registry not available\n" );
	exit( 1 );
}

$out = array(
	'extracted_at' => gmdate( 'c' ),
	'site_url'     => get_site_url(),
	'patterns'     => array(),
);

foreach ( WP_Block_Patterns_Registry::get_instance()->get_all_registered() as $p ) {
	$out['patterns'][] = array(
		'name'       => $p['name'],
		'title'      => isset( $p['title'] ) ? $p['title'] : '',
		'categories' => isset( $p['categories'] ) ? $p['categories'] : array(),
		'source'     => isset( $p['source'] ) ? $p['source'] : '',
		'inserter'   => ! isset( $p['inserter'] ) || $p['inserter'],
		'blockTypes' => isset( $p['blockTypes'] ) ? $p['blockTypes'] : array(),
		'content'    => isset( $p['content'] ) ? $p['content'] : '',
	);
}

echo wp_json_encode( $out );
