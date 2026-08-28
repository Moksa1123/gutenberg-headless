<?php
/**
 * Render EVERY registered block server-side and record what actually comes out.
 *
 *   wp eval-file tools/sweep-render.php > render-sweep.json
 *
 * Each block is serialized in its void form (<!-- wp:x /-->) - the attrs-only
 * test - and passed through do_blocks() inside a Throwable guard. Verdicts:
 *
 *   renders        the callback produced markup on a bare page, no context
 *   empty          registered, runs, produces NOTHING on a bare page - placing
 *                  it verbatim gives you an invisible page and no error
 *   content-block  has sourced attributes; its content IS the saved HTML, so a
 *                  void test would be meaningless - not swept this way
 *   error          the render callback threw (message recorded)
 *
 * "empty" is not "broken": most need context (a product, a cart, a query loop,
 * a post). The point is you must KNOW which ones those are before writing one
 * into a bare page.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit( 1 );
}

// Silence PHP notices from callbacks expecting context; keep real output only.
error_reporting( E_ERROR );

$registry = WP_Block_Type_Registry::get_instance();
$rows     = array();

// Render inside a made-up main-query-ish context as little as possible:
// a bare page, no global $post. That IS the test.
foreach ( $registry->get_all_registered() as $name => $bt ) {
	$has_sourced = false;
	foreach ( (array) $bt->attributes as $a ) {
		if ( ! empty( $a['source'] ) ) {
			$has_sourced = true;
			break;
		}
	}
	if ( $has_sourced ) {
		$rows[ $name ] = array( 'verdict' => 'content-block', 'note' => 'content is the saved HTML; void test meaningless' );
		continue;
	}

	$markup = '<!-- wp:' . preg_replace( '#^core/#', '', $name ) . ' /-->';
	try {
		ob_start();
		$out = do_blocks( $markup );
		$stray = ob_get_clean();
		$out = trim( $out . $stray );
		if ( '' === $out ) {
			$rows[ $name ] = array( 'verdict' => 'empty', 'note' => 'renders NOTHING on a bare page' );
		} else {
			$note = strlen( $out ) . 'b';
			if ( preg_match( '/class="([^"]*)"/', $out, $m ) ) {
				$note .= ' class:' . substr( $m[1], 0, 60 );
			}
			$rows[ $name ] = array( 'verdict' => 'renders', 'note' => $note );
		}
	} catch ( \Throwable $e ) {
		while ( ob_get_level() ) {
			ob_end_clean();
		}
		$rows[ $name ] = array( 'verdict' => 'error', 'note' => get_class( $e ) . ': ' . substr( $e->getMessage(), 0, 90 ) );
	}
}

echo wp_json_encode( $rows, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE );
