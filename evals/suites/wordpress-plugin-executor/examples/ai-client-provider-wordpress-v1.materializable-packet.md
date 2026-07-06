## Spec Conformance
Implements the approved Acme AI Client Smoke plugin spec with a deterministic no-auth AI Client provider and one helper that calls `wp_ai_client_prompt()` through `using_model_preference()` and `generate_text()`. It does not add REST routes, AJAX endpoints, admin-post handlers, cron, SQL, uploads, remote HTTP calls, production write commands, API keys, external provider credentials, or a real OpenAI/Anthropic/Google provider configuration. Generated paths: `acme-ai-client-smoke/acme-ai-client-smoke.php`, `acme-ai-client-smoke/includes/class-availability.php`, `acme-ai-client-smoke/includes/class-metadata-directory.php`, `acme-ai-client-smoke/includes/class-deterministic-text-model.php`, `acme-ai-client-smoke/includes/class-provider.php`, and `acme-ai-client-smoke/readme.txt`.

## Generated File Map
- `acme-ai-client-smoke/acme-ai-client-smoke.php`
- `acme-ai-client-smoke/includes/class-availability.php`
- `acme-ai-client-smoke/includes/class-metadata-directory.php`
- `acme-ai-client-smoke/includes/class-deterministic-text-model.php`
- `acme-ai-client-smoke/includes/class-provider.php`
- `acme-ai-client-smoke/readme.txt`

## Implementation Packets
### acme-ai-client-smoke/acme-ai-client-smoke.php
```php
<?php
/**
 * Plugin Name: Acme AI Client Smoke
 * Description: Registers a deterministic no-auth AI Client provider for runtime certification.
 * Version: 0.1.0
 * Requires at least: 7.0
 * Requires PHP: 8.1
 * Text Domain: acme-ai-client-smoke
 * License: GPL-2.0-or-later
 * License URI: https://www.gnu.org/licenses/gpl-2.0.html
 *
 * @package AcmeAIClientSmoke
 */

declare(strict_types=1);

namespace AcmeAIClientSmoke;

use WordPress\AiClient\AiClient;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

const PROVIDER_ID = 'acme-ai-client-smoke';
const MODEL_ID    = 'acme-deterministic-text';
const OUTPUT_TEXT = 'AI Client smoke: deterministic provider response';

require_once __DIR__ . '/includes/class-availability.php';
require_once __DIR__ . '/includes/class-metadata-directory.php';
require_once __DIR__ . '/includes/class-deterministic-text-model.php';
require_once __DIR__ . '/includes/class-provider.php';

add_action( 'init', __NAMESPACE__ . '\\register_provider', 5 );

/**
 * Register the deterministic provider with the AI Client registry.
 */
function register_provider(): void {
	if ( ! class_exists( AiClient::class ) ) {
		return;
	}

	$registry = AiClient::defaultRegistry();
	if ( $registry->hasProvider( Provider::class ) ) {
		return;
	}

	$registry->registerProvider( Provider::class );
}

/**
 * Generate a deterministic summary through the WordPress AI Client.
 *
 * @param string $prompt Prompt supplied by the runtime smoke test.
 * @return string|\WP_Error Provider response text or an error.
 */
function generate_summary( string $prompt ) {
	if ( ! current_user_can( 'edit_posts' ) ) {
		return new \WP_Error( 'acme_ai_client_smoke_forbidden', 'Current user cannot generate AI summaries.' );
	}

	if ( ! function_exists( 'wp_ai_client_prompt' ) ) {
		return new \WP_Error( 'acme_ai_client_smoke_unavailable', 'The WordPress AI Client is unavailable.' );
	}

	$result = \wp_ai_client_prompt( $prompt )
		->using_model_preference( array( PROVIDER_ID, MODEL_ID ) )
		->generate_text();

	if ( is_wp_error( $result ) ) {
		return $result;
	}

	return wp_kses_post( $result );
}
```

### acme-ai-client-smoke/includes/class-availability.php
```php
<?php
/**
 * Availability checker for the deterministic provider.
 *
 * @package AcmeAIClientSmoke
 */

declare(strict_types=1);

namespace AcmeAIClientSmoke;

use WordPress\AiClient\Providers\Contracts\ProviderAvailabilityInterface;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Reports no-auth provider availability.
 */
final class Availability implements ProviderAvailabilityInterface {
	/**
	 * This deterministic provider needs no credentials.
	 *
	 * @return bool Always true.
	 */
	public function isConfigured(): bool {
		return true;
	}
}
```

### acme-ai-client-smoke/includes/class-metadata-directory.php
```php
<?php
/**
 * Model metadata directory for the deterministic provider.
 *
 * @package AcmeAIClientSmoke
 */

declare(strict_types=1);

namespace AcmeAIClientSmoke;

use WordPress\AiClient\Messages\Enums\ModalityEnum;
use WordPress\AiClient\Providers\Contracts\ModelMetadataDirectoryInterface;
use WordPress\AiClient\Providers\Models\DTO\ModelMetadata;
use WordPress\AiClient\Providers\Models\DTO\SupportedOption;
use WordPress\AiClient\Providers\Models\Enums\CapabilityEnum;
use WordPress\AiClient\Providers\Models\Enums\OptionEnum;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Metadata directory for the deterministic text model.
 */
final class Metadata_Directory implements ModelMetadataDirectoryInterface {
	/**
	 * Build metadata for the deterministic text model.
	 *
	 * @return ModelMetadata Model metadata.
	 */
	public static function metadata(): ModelMetadata {
		return new ModelMetadata(
			MODEL_ID,
			'Acme Deterministic Text',
			array( CapabilityEnum::textGeneration() ),
			array(
				new SupportedOption( OptionEnum::inputModalities(), array( array( ModalityEnum::text() ) ) ),
				new SupportedOption( OptionEnum::outputModalities(), array( array( ModalityEnum::text() ) ) ),
			)
		);
	}

	/**
	 * List all supported model metadata.
	 *
	 * @return array<int,ModelMetadata> Supported model metadata.
	 */
	public function listModelMetadata(): array {
		return array( self::metadata() );
	}

	/**
	 * Check whether metadata exists for a model.
	 *
	 * @param string $model_id Model identifier.
	 * @return bool True when the model exists.
	 */
	public function hasModelMetadata( string $model_id ): bool {
		return MODEL_ID === $model_id;
	}

	/**
	 * Get metadata for a model.
	 *
	 * @param string $model_id Model identifier.
	 * @return ModelMetadata Model metadata.
	 * @throws \InvalidArgumentException When the model identifier is unknown.
	 */
	public function getModelMetadata( string $model_id ): ModelMetadata {
		if ( MODEL_ID !== $model_id ) {
			throw new \InvalidArgumentException( 'Requested model is not available.' );
		}

		return self::metadata();
	}
}
```

### acme-ai-client-smoke/includes/class-deterministic-text-model.php
```php
<?php
/**
 * Deterministic text generation model.
 *
 * @package AcmeAIClientSmoke
 */

declare(strict_types=1);

namespace AcmeAIClientSmoke;

use WordPress\AiClient\Messages\DTO\MessagePart;
use WordPress\AiClient\Messages\DTO\ModelMessage;
use WordPress\AiClient\Providers\DTO\ProviderMetadata;
use WordPress\AiClient\Providers\Models\Contracts\ModelInterface;
use WordPress\AiClient\Providers\Models\DTO\ModelConfig;
use WordPress\AiClient\Providers\Models\DTO\ModelMetadata;
use WordPress\AiClient\Providers\Models\TextGeneration\Contracts\TextGenerationModelInterface;
use WordPress\AiClient\Results\DTO\Candidate;
use WordPress\AiClient\Results\DTO\GenerativeAiResult;
use WordPress\AiClient\Results\DTO\TokenUsage;
use WordPress\AiClient\Results\Enums\FinishReasonEnum;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Deterministic model used by the runtime smoke test.
 */
final class Deterministic_Text_Model implements ModelInterface, TextGenerationModelInterface {
	/**
	 * Model metadata.
	 *
	 * @var ModelMetadata
	 */
	private ModelMetadata $metadata;

	/**
	 * Model configuration.
	 *
	 * @var ModelConfig
	 */
	private ModelConfig $config;

	/**
	 * Construct the deterministic model.
	 *
	 * @param ModelMetadata $metadata Model metadata.
	 * @param ModelConfig   $config Model configuration.
	 */
	public function __construct( ModelMetadata $metadata, ModelConfig $config ) {
		$this->metadata = $metadata;
		$this->config   = $config;
	}

	/**
	 * Get model metadata.
	 *
	 * @return ModelMetadata Model metadata.
	 */
	public function metadata(): ModelMetadata {
		return $this->metadata;
	}

	/**
	 * Get provider metadata.
	 *
	 * @return ProviderMetadata Provider metadata.
	 */
	public function providerMetadata(): ProviderMetadata {
		return Provider::metadata();
	}

	/**
	 * Set model configuration.
	 *
	 * @param ModelConfig $config Model configuration.
	 */
	public function setConfig( ModelConfig $config ): void {
		$this->config = $config;
	}

	/**
	 * Get model configuration.
	 *
	 * @return ModelConfig Model configuration.
	 */
	public function getConfig(): ModelConfig {
		return $this->config;
	}

	/**
	 * Return deterministic generated text.
	 *
	 * @param array<int,\WordPress\AiClient\Messages\DTO\Message> $prompt Prompt messages.
	 * @return GenerativeAiResult Text generation result.
	 */
	public function generateTextResult( array $prompt ): GenerativeAiResult {
		unset( $prompt );

		return new GenerativeAiResult(
			'acme-ai-client-smoke-result',
			array(
				new Candidate(
					new ModelMessage(
						array(
							new MessagePart( OUTPUT_TEXT ),
						)
					),
					FinishReasonEnum::stop()
				),
			),
			new TokenUsage( 4, 7, 11 ),
			Provider::metadata(),
			$this->metadata
		);
	}
}
```

### acme-ai-client-smoke/includes/class-provider.php
```php
<?php
/**
 * Deterministic AI Client provider.
 *
 * @package AcmeAIClientSmoke
 */

declare(strict_types=1);

namespace AcmeAIClientSmoke;

use WordPress\AiClient\Providers\Contracts\ModelMetadataDirectoryInterface;
use WordPress\AiClient\Providers\Contracts\ProviderAvailabilityInterface;
use WordPress\AiClient\Providers\Contracts\ProviderInterface;
use WordPress\AiClient\Providers\DTO\ProviderMetadata;
use WordPress\AiClient\Providers\Enums\ProviderTypeEnum;
use WordPress\AiClient\Providers\Models\Contracts\ModelInterface;
use WordPress\AiClient\Providers\Models\DTO\ModelConfig;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Deterministic no-auth provider for the AI Client smoke test.
 */
final class Provider implements ProviderInterface {
	/**
	 * Get provider metadata.
	 *
	 * @return ProviderMetadata Provider metadata.
	 */
	public static function metadata(): ProviderMetadata {
		return new ProviderMetadata(
			PROVIDER_ID,
			'Acme AI Client Smoke',
			ProviderTypeEnum::server(),
			null,
			null,
			'Deterministic no-auth provider for AI Client runtime smoke tests.'
		);
	}

	/**
	 * Create the deterministic model instance.
	 *
	 * @param string           $model_id Model identifier.
	 * @param ModelConfig|null $model_config Optional model configuration.
	 * @return ModelInterface Model instance.
	 * @throws \InvalidArgumentException When the model identifier is unknown.
	 */
	public static function model( string $model_id, ?ModelConfig $model_config = null ): ModelInterface {
		if ( MODEL_ID !== $model_id ) {
			throw new \InvalidArgumentException( 'Requested model is not available.' );
		}

		return new Deterministic_Text_Model( Metadata_Directory::metadata(), $model_config ?? new ModelConfig() );
	}

	/**
	 * Get provider availability checker.
	 *
	 * @return ProviderAvailabilityInterface Availability checker.
	 */
	public static function availability(): ProviderAvailabilityInterface {
		return new Availability();
	}

	/**
	 * Get the model metadata directory.
	 *
	 * @return ModelMetadataDirectoryInterface Metadata directory.
	 */
	public static function modelMetadataDirectory(): ModelMetadataDirectoryInterface {
		return new Metadata_Directory();
	}
}
```

### acme-ai-client-smoke/readme.txt
```txt
=== Acme AI Client Smoke ===
Contributors: acme
Requires at least: 7.0
Tested up to: 7.0
Requires PHP: 8.1
Stable tag: 0.1.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

Registers the acme-ai-client-smoke deterministic provider and acme-deterministic-text model for AI Client runtime certification.

== Description ==

Acme AI Client Smoke registers a no-auth deterministic server provider with WordPress AI Client so runtime smoke tests can prove provider registry, connector registration, model preference selection, and generated text flow without API keys or external network calls.
```

## Security Notes
The plugin registers a deterministic no-auth provider on `init` and exposes no public HTTP, REST, AJAX, admin-post, cron, SQL, upload, or file-write surface. The only helper, `AcmeAIClientSmoke\generate_summary()`, requires `current_user_can( 'edit_posts' )`, checks `function_exists( 'wp_ai_client_prompt' )`, calls `wp_ai_client_prompt()->using_model_preference()->generate_text()`, handles `is_wp_error()`, and returns escaped text through `wp_kses_post()`. The provider does not use API keys, environment variables, external provider credentials, or outbound HTTP; it is a local deterministic test double for the WordPress AI Client provider boundary.

## Deviation Log
No deviations from the approved spec. This fixture intentionally uses a no-auth deterministic provider instead of OpenAI, Anthropic, Google, or another API-key provider so the runtime proof can run in disposable `wp-env` without secrets or network dependencies. It proves local AI Client provider selection and connector registration, not third-party model quality or credential handling.

## Verification Notes
- Run `python3 evals/harness/certify_wordpress_executor_artifact.py --executor plugin --packet evals/suites/wordpress-plugin-executor/examples/ai-client-provider-wordpress-v1.materializable-packet.md --out-dir evals/results/wordpress-skill-candidate-eval/generated-ai-client-provider-artifact-cert-YYYYMMDD/generated-plugin --result-dir evals/results/wordpress-skill-candidate-eval/generated-ai-client-provider-artifact-cert-YYYYMMDD --overwrite` for packet, materialization, static artifact, AI-surface heuristic, and PHP syntax gates.
- Run `python3 evals/harness/run_wordpress_runtime_smoke.py --artifact-path evals/results/wordpress-skill-candidate-eval/generated-ai-client-provider-artifact-cert-YYYYMMDD/generated-plugin/acme-ai-client-smoke --ai-client-smoke --ai-client-provider-id acme-ai-client-smoke --ai-client-model-id acme-deterministic-text --ai-client-helper-function 'AcmeAIClientSmoke\generate_summary' --ai-client-prompt "Runtime AI Client smoke" --ai-client-expected-output "AI Client smoke: deterministic provider response" --provision-full-profile --write --run-id generated-ai-client-provider-full-profile-YYYYMMDD --timeout-sec 300` to copy the generated plugin into disposable `wp-env`, activate it in WordPress 7.0, verify the provider through `wp_ai_client_prompt()`, require connector/provider evidence, and require WPCS/PHPCS plus Plugin Check.
- Run WP-CLI smoke commands in that disposable environment, including `wp plugin activate acme-ai-client-smoke` and a `wp --user=admin eval` call that invokes `AcmeAIClientSmoke\generate_summary()`, before claiming runtime availability.
- Run PHPCS/WPCS with `phpcs --standard=WordPress --extensions=php <generated-plugin-dir>/acme-ai-client-smoke` before coding-standards claims if the provisioned full profile is not used.
- Run PHPUnit when a test suite exists; this minimal AI Client fixture intentionally has no PHPUnit suite, so no PHPUnit proof is claimed.
- Run Plugin Check with `wp plugin check acme-ai-client-smoke` before release claims.
- This packet does not prove real external provider credentials, OpenAI/Anthropic/Google API behavior, browser/editor behavior, MCP Adapter behavior, long-run model variance, public package extraction, or release readiness.

## Critic Handoff
Send the materialized files, certification output, and AI Client runtime smoke output to `wordpress-security-critic` for capability, no-secret, credential-boundary, and provider-registration review, then to `wordpress-critic` for architecture, runtime-boundary, release-readiness, and operational calibration.
