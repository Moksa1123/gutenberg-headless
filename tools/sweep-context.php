<?php
/**
 * Render every registered block in progressively richer CONTEXTS and record the
 * first one in which it produces output.
 *
 *   wp eval-file tools/sweep-context.php > data/render-context.json
 *   wp eval-file tools/sweep-context.php 444 4412      # post ID, product ID
 *
 * WHY THIS EXISTS
 * sweep-render.php answers "does this block render on a bare page", and for 209
 * of 302 blocks on the reference site the answer is no. That verdict is true
 * and nearly useless on its own: it does not say whether the block is broken,
 * needs a post, needs a product, or needs to be inside a query loop. Publishing
 * the page is currently the only way to find out, which is exactly the
 * silent-failure loop this skill exists to close.
 *
 * So each block is rendered again inside contexts that a real page can provide,
 * cheapest first, and the FIRST one that yields output is recorded:
 *
 *   bare        no context at all - what sweep-render.php measures
 *   singular    a real published post is the global $post and the main query
 *               says is_singular(); this is what a normal page gives a block
 *   query-loop  wrapped in core/query + core/post-template, so the block
 *               receives postId / postType through block CONTEXT rather than
 *               through globals - a different mechanism, and the one most
 *               post-* blocks actually need
 *   product     a real product is the global $post and wc_setup_product_data()
 *               has run - what a single-product template provides
 *
 * A block that renders in none of them needs something this script does not
 * build (a cart with contents, a checkout session, a term archive), and that is
 * recorded as `needs-more` rather than guessed at.
 */

if ( ! defined( 'ABSPATH' ) ) {
	fwrite( STDERR, "Run via: wp eval-file tools/sweep-context.php\n" );
	exit( 1 );
}

$post_id    = ! empty( $args[0] ) ? (int) $args[0] : 0;
$product_id = ! empty( $args[1] ) ? (int) $args[1] : 0;

if ( ! $post_id ) {
	$p       = get_posts( array( 'numberposts' => 1, 'post_type' => 'post', 'post_status' => 'publish' ) );
	$post_id = $p ? $p[0]->ID : 0;
}
if ( ! $product_id && post_type_exists( 'product' ) ) {
	$p          = get_posts( array( 'numberposts' => 1, 'post_type' => 'product', 'post_status' => 'publish' ) );
	$product_id = $p ? $p[0]->ID : 0;
}

/** Render one block's void form and return the trimmed output, or ''. */
function gbx_render( $markup ) {
	try {
		$out = do_blocks( $markup );
	} catch ( \Throwable $e ) {
		return array( '', 'ERROR: ' . $e->getMessage() );
	}
	return array( trim( wp_strip_all_tags( $out, true ) ) === '' && trim( $out ) === '' ? '' : $out, null );
}

/**
 * Enter and LEAVE a singular context.
 *
 * The first version of this script entered a context per block and left it
 * again, and the results were worthless: `wp_reset_postdata()` restores $post
 * from $wp_query->post, which is the very value enter() had just set, so the
 * context never actually ended. From the first block that needed a post
 * onwards, every later block's "bare" test ran with a post still in scope -
 * core/post-content reported 3,849 bytes of "bare" output, which is the post's
 * own content. Contexts are now entered ONCE per pass, and the globals are
 * snapshotted and written back wholesale.
 */
function gbx_snapshot() {
	global $post, $wp_query;
	return array( 'post' => $post, 'query' => clone $wp_query );
}

function gbx_restore( $snap ) {
	global $post, $wp_query;
	$post     = $snap['post'];
	$wp_query = $snap['query'];
	if ( function_exists( 'wc_setup_product_data' ) ) {
		$GLOBALS['product'] = null;
	}
}

function gbx_enter_singular( $id ) {
	global $post, $wp_query;
	$post = get_post( $id );
	setup_postdata( $post );
	$wp_query->post              = $post;
	$wp_query->posts             = array( $post );
	$wp_query->queried_object    = $post;
	$wp_query->queried_object_id = $id;
	$wp_query->is_singular       = true;
	$wp_query->is_single         = 'post' === $post->post_type;
	$wp_query->is_page           = 'page' === $post->post_type;
	$wp_query->is_home           = false;
	$wp_query->post_count        = 1;
	$wp_query->found_posts       = 1;
}

$registry = WP_Block_Type_Registry::get_instance();
$names    = array_keys( $registry->get_all_registered() );
$void     = array();
foreach ( $names as $n ) {
	$void[ $n ] = '<!-- wp:' . ( 0 === strpos( $n, 'core/' ) ? substr( $n, 5 ) : $n ) . ' /-->';
}

$hit   = array();   // block => first context that produced output
$bytes = array();
$errors = array();

// A pass renders every block once, in one context, and records only blocks that
// have not already been explained by a cheaper context.
$pass = function ( $label, callable $render ) use ( $names, &$hit, &$bytes, &$errors ) {
	foreach ( $names as $n ) {
		if ( isset( $hit[ $n ] ) ) {
			continue;
		}
		try {
			$len = $render( $n );
		} catch ( \Throwable $e ) {
			$errors[ $n ] = substr( $e->getMessage(), 0, 120 );
			$hit[ $n ]    = 'error';
			continue;
		}
		if ( $len > 0 ) {
			$hit[ $n ]   = $label;
			$bytes[ $n ] = $len;
		}
	}
};

// ---- pass 1: bare. Clear the globals first so it really is bare. -----------
$boot = gbx_snapshot();
$GLOBALS['post'] = null;
$pass( 'bare', function ( $n ) use ( $void ) {
	return strlen( trim( do_blocks( $void[ $n ] ) ) );
} );
gbx_restore( $boot );

// ---- pass 2: a real post is the global $post and the query agrees ---------
if ( $post_id ) {
	$snap = gbx_snapshot();
	gbx_enter_singular( $post_id );
	$pass( 'singular', function ( $n ) use ( $void ) {
		return strlen( trim( do_blocks( $void[ $n ] ) ) );
	} );
	gbx_restore( $snap );
}

// ---- pass 3: inside core/query + core/post-template ------------------------
// Context reaches the block through the block TREE here, not through globals -
// a different mechanism, and the one most post-* blocks are written for.
if ( $post_id ) {
	$snap = gbx_snapshot();
	$GLOBALS['post'] = null;
	$wrap = function ( $inner ) {
		return '<!-- wp:query {"query":{"perPage":1,"postType":"post","inherit":false}} -->'
			. '<div class="wp-block-query"><!-- wp:post-template -->'
			. $inner
			. '<!-- /wp:post-template --></div><!-- /wp:query -->';
	};
	$baseline = strlen( trim( do_blocks( $wrap( '' ) ) ) );
	$pass( 'query-loop', function ( $n ) use ( $void, $wrap, $baseline ) {
		$len = strlen( trim( do_blocks( $wrap( $void[ $n ] ) ) ) );
		return $len > $baseline + 8 ? $len - $baseline : 0;
	} );
	gbx_restore( $snap );
}

// ---- pass 4: a real product, with WooCommerce's own globals set up ---------
if ( $product_id && function_exists( 'wc_setup_product_data' ) ) {
	$snap = gbx_snapshot();
	gbx_enter_singular( $product_id );
	wc_setup_product_data( get_post( $product_id ) );
	$pass( 'product', function ( $n ) use ( $void ) {
		return strlen( trim( do_blocks( $void[ $n ] ) ) );
	} );
	gbx_restore( $snap );
}

// ---- pass 5: a taxonomy term is the queried object ------------------------
// core/term-name, term-description, term-count and query-title read a TERM, and
// no amount of post context reaches them.
$term = null;
foreach ( array( 'category', 'product_cat', 'post_tag' ) as $tax ) {
	if ( ! taxonomy_exists( $tax ) ) {
		continue;
	}
	$t = get_terms( array( 'taxonomy' => $tax, 'number' => 1, 'hide_empty' => false ) );
	if ( ! is_wp_error( $t ) && $t ) {
		$term = $t[0];
		break;
	}
}
if ( $term ) {
	$snap = gbx_snapshot();
	global $wp_query;
	$GLOBALS['post']             = null;
	$wp_query->is_singular       = false;
	$wp_query->is_archive        = true;
	$wp_query->is_tax            = true;
	$wp_query->is_category       = ( 'category' === $term->taxonomy );
	$wp_query->queried_object    = $term;
	$wp_query->queried_object_id = $term->term_id;
	$pass( 'term-archive', function ( $n ) use ( $void ) {
		return strlen( trim( do_blocks( $void[ $n ] ) ) );
	} );
	gbx_restore( $snap );
}

// ---- pass 6: somebody is logged in ----------------------------------------
// Account, points and membership blocks render nothing for a visitor and are
// not broken; they are waiting for a user.
$admin = get_users( array( 'role' => 'administrator', 'number' => 1 ) );
if ( $admin ) {
	$prev = get_current_user_id();
	wp_set_current_user( $admin[0]->ID );
	$snap = gbx_snapshot();
	$pass( 'logged-in', function ( $n ) use ( $void ) {
		return strlen( trim( do_blocks( $void[ $n ] ) ) );
	} );
	gbx_restore( $snap );
	wp_set_current_user( $prev );
}

$results = array();
foreach ( $names as $n ) {
	$results[ $n ] = array(
		'context' => isset( $hit[ $n ] ) ? $hit[ $n ] : 'needs-more',
		'bytes'   => isset( $bytes[ $n ] ) ? $bytes[ $n ] : 0,
		'note'    => isset( $errors[ $n ] ) ? $errors[ $n ] : null,
	);
}

echo wp_json_encode( array(
	'extracted_at' => gmdate( 'c' ),
	'site_url'     => get_site_url(),
	'fixtures'     => array( 'post' => $post_id, 'product' => $product_id ),
	'blocks'       => $results,
) );
