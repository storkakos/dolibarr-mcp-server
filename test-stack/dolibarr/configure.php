<?php
/**
 * TEST ONLY. Configures the test stack's Dolibarr 23 through Dolibarr's own functions (activateModule,
 * dolibarr_set_const, User::addrights, the business object classes). No core code is changed.
 * Idempotent: runs on every start of the Dolibarr container (see 50-test-stack.sh).
 *
 *   php configure.php        (as www-data, with the environment of the dolibarr service in compose.yaml)
 *
 * Environment (all set in compose.yaml):
 *   TEST_MCP_RESOURCE          allowed resource (RFC 8707): the MCP server's public URL
 *   TEST_REDIRECT_ALLOWLIST    allowed redirect URIs for dynamic client registration, comma-separated
 *   TEST_OIDC_ISSUER           Keycloak realm URL, e.g. https://sso.example.com/realms/example
 *   TEST_OIDC_CLIENT_ID        Keycloak client for the Dolibarr login (openid_connect)
 *   TEST_OIDC_CLIENT_SECRET    its secret (test value)
 *
 * Every password and secret in the test stack is a test value.
 */
if (php_sapi_name() !== 'cli') {
	die('CLI only');
}

function env_required($name)
{
	$v = getenv($name);
	if ($v === false || trim($v) === '') {
		fwrite(STDERR, "configure.php: environment variable $name is not set\n");
		exit(2);
	}
	return trim($v);
}

$mcpResource = env_required('TEST_MCP_RESOURCE');
$redirectAllowlist = array_values(array_filter(array_map('trim', explode(',', env_required('TEST_REDIRECT_ALLOWLIST')))));
$oidcIssuer = rtrim(env_required('TEST_OIDC_ISSUER'), '/');
$oidcClientId = env_required('TEST_OIDC_CLIENT_ID');
$oidcClientSecret = env_required('TEST_OIDC_CLIENT_SECRET');

// Test users. The Dolibarr login equals the Keycloak preferred_username: Dolibarr 23 does not create
// users on the first openid_connect login. No Dolibarr password: they log in through Keycloak only.
// anna has the connect right and sees only the customers she is sales representative of (no
// societe.client.voir); bob has the same read rights but not the connect right.
$readRights = array(
	array('societe', 'lire'),
	array('facture', 'lire'),
	array('propale', 'lire'),
	array('commande', 'lire'),
	array('produit', 'lire'),
);
$testUsers = array(
	'anna' => array('firstname' => 'Anna', 'lastname' => 'Agent', 'email' => 'anna@example.com',
		'rights' => array_merge(array(array('restoauth', 'connect')), $readRights), 'sales_rep_of' => array('North Customer Ltd')),
	'bob' => array('firstname' => 'Bob', 'lastname' => 'Support', 'email' => 'bob@example.com',
		'rights' => $readRights, 'sales_rep_of' => array()),
);

define('NOSESSION', '1');
define('NOREQUIREMENU', '1');
define('NOREQUIREHTML', '1');
define('NOREQUIREAJAX', '1');
$_SERVER['REQUEST_METHOD'] = 'GET';
$htdocs = '/var/www/html';
chdir($htdocs);
require_once $htdocs.'/master.inc.php';
require_once DOL_DOCUMENT_ROOT.'/core/lib/admin.lib.php';
require_once DOL_DOCUMENT_ROOT.'/user/class/user.class.php';

function step($msg)
{
	echo "  - $msg\n";
}

function fail($msg)
{
	fwrite(STDERR, "configure.php: $msg\n");
	exit(1);
}

$admin = new User($db);
if ($admin->fetch(0, 'admin') <= 0) {
	fail('user admin not found');
}
$admin->loadRights();
$user = $admin;
$langs->loadLangs(array('main', 'admin'));

// 1. Modules: API REST, third parties, invoices, proposals, orders, products, scheduled jobs, restoauth.
// The order already satisfies the dependencies, so activate without them (otherwise modApi would be
// initialised twice in the same run).
foreach (array('modApi', 'modSociete', 'modFacture', 'modPropale', 'modCommande', 'modProduct', 'modService', 'modCron', 'modRestOAuth') as $mod) {
	$res = activateModule($mod, 0);
	if (!empty($res['errors'])) {
		fail("enabling $mod: ".implode('; ', $res['errors']));
	}
	step("module $mod enabled");
}
$conf->setValues($db);
$admin->loadRights('', 1);

// 2. Constants
$oidcBase = $oidcIssuer.'/protocol/openid-connect';
$consts = array(
	// Off: the core token table is broken in Dolibarr 23.0.3; restoauth maps its tokens with a hook.
	// Existing DOLAPIKEY integrations keep working that way.
	'API_IN_TOKEN_TABLE' => array('0', 0),
	'RESTOAUTH_RESOURCES' => array($mcpResource, $conf->entity),
	'RESTOAUTH_REDIRECT_ALLOWLIST' => array(implode("\n", $redirectAllowlist), $conf->entity),
	'RESTOAUTH_ALLOW_LOOPBACK' => array('0', $conf->entity),
	// Log in to the web interface through Keycloak (openid_connect). Dolibarr calls the token and
	// userinfo endpoints over HTTPS; the container trusts the test CA (50-test-stack.sh).
	'MAIN_AUTHENTICATION_OIDC_ON' => array('1', 0),
	'MAIN_AUTHENTICATION_OIDC_CLIENT_ID' => array($oidcClientId, 0),
	'MAIN_AUTHENTICATION_OIDC_CLIENT_SECRET' => array($oidcClientSecret, 0),
	'MAIN_AUTHENTICATION_OIDC_SCOPES' => array('openid email profile', 0),
	'MAIN_AUTHENTICATION_OIDC_LOGIN_CLAIM' => array('preferred_username', 0),
	'MAIN_AUTHENTICATION_OIDC_AUTHORIZE_URL' => array($oidcBase.'/auth', 0),
	'MAIN_AUTHENTICATION_OIDC_TOKEN_URL' => array($oidcBase.'/token', 0),
	'MAIN_AUTHENTICATION_OIDC_USERINFO_URL' => array($oidcBase.'/userinfo', 0),
	// Dolibarr 23 appends "?client_id=..&returnTo=.." (Auth0 style); Keycloak only knows
	// post_logout_redirect_uri. So both go here: after logout the browser lands on Dolibarr's login page.
	'MAIN_AUTHENTICATION_OIDC_LOGOUT_URL' => array($oidcBase.'/logout?client_id='.rawurlencode($oidcClientId)
		.'&post_logout_redirect_uri='.rawurlencode(DOL_MAIN_URL_ROOT.'/index.php'), 0),
	'MAIN_LANG_DEFAULT' => array('en_US', $conf->entity),
);
// Without a company name and country Dolibarr sends every login to admin/index.php
// ("setupnotcomplete"), and non-admins only see "access denied". Only set when still empty.
if (!getDolGlobalString('MAIN_INFO_SOCIETE_NOM')) {
	$consts['MAIN_INFO_SOCIETE_NOM'] = array('Example Company', $conf->entity);
}
if (!getDolGlobalString('MAIN_INFO_SOCIETE_COUNTRY')) {
	$consts['MAIN_INFO_SOCIETE_COUNTRY'] = array('5:DE:Germany', $conf->entity);
}
foreach ($consts as $name => $v) {
	if (dolibarr_set_const($db, $name, $v[0], 'chaine', 0, 'dolibarr-mcp test stack', $v[1]) < 0) {
		fail("setting $name: ".$db->lasterror());
	}
	step("$name set");
}
$conf->setValues($db);

// 3. Sample data: products, two customers, and per customer one invoice, proposal and order (validated).
require_once DOL_DOCUMENT_ROOT.'/product/class/product.class.php';
require_once DOL_DOCUMENT_ROOT.'/societe/class/societe.class.php';
require_once DOL_DOCUMENT_ROOT.'/compta/facture/class/facture.class.php';
require_once DOL_DOCUMENT_ROOT.'/comm/propal/class/propal.class.php';
require_once DOL_DOCUMENT_ROOT.'/commande/class/commande.class.php';

$products = array();
foreach (array(
	'SRV-MAINT' => array('Maintenance (hour)', Product::TYPE_SERVICE, 100),
	'HW-ROUTER' => array('Router', Product::TYPE_PRODUCT, 250),
) as $ref => $p) {
	$prod = new Product($db);
	if ($prod->fetch(0, $ref) <= 0) {
		$prod->ref = $ref;
		$prod->label = $p[0];
		$prod->type = $p[1];
		$prod->price = $p[2];
		$prod->price_base_type = 'HT';
		$prod->tva_tx = 19;
		$prod->status = 1;
		$prod->status_buy = 1;
		if ($prod->create($admin) <= 0) {
			fail("product $ref: ".$prod->error.' '.implode('; ', $prod->errors));
		}
		step("product $ref created");
	}
	$products[$ref] = $prod;
}

$customers = array();
foreach (array('North Customer Ltd' => 'Hamburg', 'South Customer Inc' => 'Munich') as $name => $town) {
	$soc = new Societe($db);
	if ($soc->fetch(0, $name) > 0) {
		$customers[$name] = $soc;
		continue;
	}
	$soc->name = $name;
	$soc->client = 1;
	$soc->code_client = -1;
	$soc->town = $town;
	$soc->country_id = 5; // DE
	if ($soc->create($admin) <= 0) {
		fail("third party $name: ".$soc->error.' '.implode('; ', $soc->errors));
	}
	$customers[$name] = $soc;

	$inv = new Facture($db);
	$inv->socid = $soc->id;
	$inv->date = dol_now();
	$inv->type = Facture::TYPE_STANDARD;
	$inv->cond_reglement_id = 1;
	$inv->note_public = 'Test stack invoice for '.$name;
	if ($inv->create($admin) <= 0
		|| $inv->addline('Maintenance', 100, 2, 19, 0, 0, $products['SRV-MAINT']->id) <= 0
		|| $inv->validate($admin) <= 0) {
		fail("invoice for $name: ".$inv->error.' '.implode('; ', $inv->errors));
	}

	$prop = new Propal($db);
	$prop->socid = $soc->id;
	$prop->datep = dol_now();
	$prop->duree_validite = 30;
	$prop->cond_reglement_id = 1;
	if ($prop->create($admin) <= 0
		|| $prop->addline('Router', 250, 1, 19, 0, 0, $products['HW-ROUTER']->id) <= 0
		|| $prop->valid($admin) <= 0) {
		fail("proposal for $name: ".$prop->error.' '.implode('; ', $prop->errors));
	}

	$ord = new Commande($db);
	$ord->socid = $soc->id;
	$ord->date = dol_now();
	$ord->cond_reglement_id = 1;
	if ($ord->create($admin) <= 0
		|| $ord->addline('Router', 250, 1, 19, 0, 0, $products['HW-ROUTER']->id) <= 0
		|| $ord->valid($admin) <= 0) {
		fail("order for $name: ".$ord->error.' '.implode('; ', $ord->errors));
	}
	step("third party $name with invoice {$inv->ref}, proposal {$prop->ref}, order {$ord->ref}");
}

// 4. Test users and their rights
foreach ($testUsers as $login => $u) {
	$tu = new User($db);
	if ($tu->fetch(0, $login) <= 0) {
		$tu->login = $login;
		$tu->firstname = $u['firstname'];
		$tu->lastname = $u['lastname'];
		$tu->email = $u['email'];
		$tu->admin = 0;
		$tu->entity = 1;
		if ($tu->create($admin) <= 0) {
			fail("user $login: ".$tu->error);
		}
		step("user $login created (login through Keycloak only, no Dolibarr password)");
	}
	foreach ($u['rights'] as $r) {
		$sql = "SELECT id FROM ".$db->prefix()."rights_def WHERE module = '".$db->escape($r[0])."' AND perms = '".$db->escape($r[1])."'"
			." AND (subperms IS NULL OR subperms = '') AND entity = ".((int) $conf->entity);
		$resq = $db->query($sql);
		$o = $resq ? $db->fetch_object($resq) : null;
		if (!$o) {
			fail("right $r[0].$r[1] not found");
		}
		if ($tu->addrights((int) $o->id) < 0) {
			fail("granting $r[0].$r[1] to $login: ".$tu->error);
		}
	}
	step("user $login: rights ".implode(', ', array_map(function ($r) {
		return $r[0].'.'.$r[1];
	}, $u['rights'])));
	foreach ($u['sales_rep_of'] as $name) {
		$customers[$name]->add_commercial($admin, $tu->id);
		step("$login is sales representative of $name");
	}
}

echo "Dolibarr configured\n";
