<?php
/**
 * The base configuration for WordPress
 *
 * The wp-config.php creation script uses this file during the installation.
 * You don't have to use the web site, you can copy this file to "wp-config.php"
 * and fill in the values.
 *
 * This file contains the following configurations:
 *
 * * Database settings
 * * Secret keys
 * * Database table prefix
 * * Localized language
 * * ABSPATH
 *
 * @link https://wordpress.org/support/article/editing-wp-config-php/
 *
 * @package WordPress
 */

// ** Database settings - You can get this info from your web host ** //
/** The name of the database for WordPress */
define( 'DB_NAME', 'local' );

/** Database username */
define( 'DB_USER', 'root' );

/** Database password */
define( 'DB_PASSWORD', 'root' );

/** Database hostname */
define( 'DB_HOST', 'localhost' );

/** Database charset to use in creating database tables. */
define( 'DB_CHARSET', 'utf8' );

/** The database collate type. Don't change this if in doubt. */
define( 'DB_COLLATE', '' );

/**#@+
 * Authentication unique keys and salts.
 *
 * Change these to different unique phrases! You can generate these using
 * the {@link https://api.wordpress.org/secret-key/1.1/salt/ WordPress.org secret-key service}.
 *
 * You can change these at any point in time to invalidate all existing cookies.
 * This will force all users to have to log in again.
 *
 * @since 2.6.0
 */
define( 'AUTH_KEY',          'f*BG[J./I75W.d_o%<Ng#U>R@bG%eHa.;JnlGvRLvG}V<bZh1u3Wnq/a8F#]3-Qf' );
define( 'SECURE_AUTH_KEY',   'H05G|XB-C>JsFQ.rR)q<~|H_#bbZ,!G6v]Sh1@iBw1#/O7!ti[iToH7e!*s^je2L' );
define( 'LOGGED_IN_KEY',     'sKcT#hm:}-DEsepR:8I<s4+,N5 n?89jf~d.|4]`5MI+4:-:D!6WZZ@QkMq}22O?' );
define( 'NONCE_KEY',         'o)b6E`#-%eIAfw4~G{UT$D/f]dM:.K ed+Jrlm6zo=T)Zt!&qCnv)]$:,L |wx0]' );
define( 'AUTH_SALT',         '(&VNnh!J>PM*?<}.f3@O&_K!3DZ%JC,:IfS*,cOEs}hg7(pV%El>-5<WI64[?Yi<' );
define( 'SECURE_AUTH_SALT',  'Tf1.)y7RT5%$Ce?mPAO6D]H>{|PYHx@y7c_7+dsFy.]@LduX1]c-:5O%>Uw_KRVz' );
define( 'LOGGED_IN_SALT',    'b>1d!N*-dt3y|:j6)vlg*X;(g)k`M3r83#][Hvg,wnBz%-_Q#t]G5W&%{kOWREE+' );
define( 'NONCE_SALT',        '8UVhP4KVT}eoTFGp:`v?p;|vo~eTn=MaJEQU@fbJ^?a(H9JKie~|jI$QezlgS UM' );
define( 'WP_CACHE_KEY_SALT', '$iVXrZG,$}}5(j15)ha1o,BeR:Kl)Dc-)iYnw1!|]-32J~EqeX_B{%Z3j#T~o7/v' );


/**#@-*/

/**
 * WordPress database table prefix.
 *
 * You can have multiple installations in one database if you give each
 * a unique prefix. Only numbers, letters, and underscores please!
 */
$table_prefix = 'wp_';


/* Add any custom values between this line and the "stop editing" line. */



/**
 * For developers: WordPress debugging mode.
 *
 * Change this to true to enable the display of notices during development.
 * It is strongly recommended that plugin and theme developers use WP_DEBUG
 * in their development environments.
 *
 * For information on other constants that can be used for debugging,
 * visit the documentation.
 *
 * @link https://wordpress.org/support/article/debugging-in-wordpress/
 */
define( 'WP_DEBUG', false );
define( 'WP_DEBUG_LOG', false );
define( 'SCRIPT_DEBUG', false );
define( 'WP_ENVIRONMENT_TYPE', 'local' );
define( 'WP_HTTP_BLOCK_EXTERNAL', true );
define( 'AUTOMATIC_UPDATER_DISABLED', true );
/* That's all, stop editing! Happy publishing. */

/** Absolute path to the WordPress directory. */
if ( ! defined( 'ABSPATH' ) ) {
	define( 'ABSPATH', __DIR__ . '/' );
}

/** Sets up WordPress vars and included files. */
require_once ABSPATH . 'wp-settings.php';
