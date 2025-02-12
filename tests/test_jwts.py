import json
import time
from typing import Any, Dict

import jwt
import pkg_resources
import pytest

from guardpost.jwks import JWKS, InMemoryKeysProvider, KeysProvider
from guardpost.jwks.caching import CachingKeysProvider
from guardpost.jwks.openid import AuthorityKeysProvider
from guardpost.jwks.urls import URLKeysProvider
from guardpost.jwts import InvalidAccessToken, JWTValidator


def get_file_path(file_name, folder_name: str = "res") -> str:
    return pkg_resources.resource_filename(__name__, f"./{folder_name}/{file_name}")


def get_test_jwks() -> JWKS:
    with open(get_file_path("jwks.json"), mode="rt", encoding="utf8") as jwks_file:
        jwks_dict = json.loads(jwks_file.read())
    return JWKS.from_dict(jwks_dict)


@pytest.fixture(scope="session")
def default_keys_provider() -> KeysProvider:
    return InMemoryKeysProvider(get_test_jwks())


def get_access_token(
    kid: str, payload: Dict[str, Any], include_headers: bool = True, fake_kid: str = ""
):
    # loads the private key, use it to create an access token
    # return the access token
    with open(get_file_path(f"{kid}.pem"), "r") as key_file:
        private_key = key_file.read()

    return jwt.encode(
        payload,
        private_key,
        algorithm="RS256",
        headers={"kid": fake_kid or kid} if include_headers else None,
    )


async def _valid_tokens_scenario(validator: JWTValidator, include_headers: bool = True):
    for i in range(5):
        payload = {"aud": "a", "iss": "b"}
        valid_token = get_access_token(str(i), payload, include_headers=include_headers)

        value = await validator.validate_jwt(valid_token)

        assert value == payload


def test_jwt_validator_raises_for_missing_key_source():
    with pytest.raises(TypeError):
        JWTValidator(valid_audiences=["a"], valid_issuers=["b"])


@pytest.mark.asyncio
async def test_jwt_validator_can_validate_valid_access_tokens(default_keys_provider):
    validator = JWTValidator(
        valid_audiences=["a"], valid_issuers=["b"], keys_provider=default_keys_provider
    )
    await _valid_tokens_scenario(validator)


@pytest.mark.asyncio
async def test_jwt_validator_cache_expiration(default_keys_provider):
    validator = JWTValidator(
        valid_audiences=["a"],
        valid_issuers=["b"],
        keys_provider=default_keys_provider,
        cache_time=0.1,
    )
    await _valid_tokens_scenario(validator)
    time.sleep(0.2)
    await _valid_tokens_scenario(validator)


@pytest.mark.asyncio
async def test_jwt_validator_blocks_forged_access_tokens(default_keys_provider):
    validator = JWTValidator(
        valid_audiences=["a"], valid_issuers=["b"], keys_provider=default_keys_provider
    )
    payload = {"aud": "a", "iss": "b"}
    forged_token = get_access_token("x", payload, fake_kid="1")

    with pytest.raises(InvalidAccessToken):
        await validator.validate_jwt(forged_token)


@pytest.mark.asyncio
async def test_jwt_validator_blocks_forged_access_tokens_no_kid(default_keys_provider):
    validator = JWTValidator(
        valid_audiences=["a"],
        valid_issuers=["b"],
        keys_provider=default_keys_provider,
        require_kid=False,
    )
    payload = {"aud": "a", "iss": "b"}
    forged_token = get_access_token("x", payload, fake_kid="1", include_headers=False)

    with pytest.raises(InvalidAccessToken):
        await validator.validate_jwt(forged_token)


@pytest.mark.asyncio
async def test_jwt_validator_blocks_invalid_kid(default_keys_provider):
    validator = JWTValidator(
        valid_audiences=["a"], valid_issuers=["b"], keys_provider=default_keys_provider
    )
    payload = {"aud": "a", "iss": "b"}
    forged_token = get_access_token("x", payload)

    with pytest.raises(InvalidAccessToken):
        await validator.validate_jwt(forged_token)


@pytest.mark.asyncio
async def test_jwt_validator_can_validate_access_tokens_from_well_known_oidc_conf():
    authority = (
        "https://raw.githubusercontent.com/Neoteroi/BlackSheep-Examples/jwks/.res"
    )
    validator = JWTValidator(
        valid_audiences=["a"], valid_issuers=["b"], authority=authority
    )

    keys_provider = validator._keys_provider
    assert isinstance(keys_provider, CachingKeysProvider)
    keys_provider = keys_provider.keys_provider
    assert isinstance(keys_provider, AuthorityKeysProvider)
    assert keys_provider.authority == authority

    await _valid_tokens_scenario(validator)


@pytest.mark.asyncio
async def test_jwt_validator_can_validate_access_tokens_from_url():
    url = (
        "https://raw.githubusercontent.com/Neoteroi/BlackSheep-Examples/jwks/.res/"
        ".well-known/jwks.json"
    )
    validator = JWTValidator(valid_audiences=["a"], valid_issuers=["b"], keys_url=url)

    keys_provider = validator._keys_provider
    assert isinstance(keys_provider, CachingKeysProvider)
    keys_provider = keys_provider.keys_provider
    assert isinstance(keys_provider, URLKeysProvider)
    assert keys_provider.url == url

    await _valid_tokens_scenario(validator)


@pytest.mark.asyncio
async def test_jwt_validator_raises_for_missing_key_id(default_keys_provider):
    validator = JWTValidator(
        valid_audiences=["a"], valid_issuers=["b"], keys_provider=default_keys_provider
    )

    payload = {"aud": "a", "iss": "b"}
    valid_token = get_access_token("0", payload, include_headers=False)

    with pytest.raises(InvalidAccessToken):
        await validator.validate_jwt(valid_token)


@pytest.mark.asyncio
async def test_jwt_validator_supports_missing_key_id_by_configuration(
    default_keys_provider,
):
    validator = JWTValidator(
        valid_audiences=["a"],
        valid_issuers=["b"],
        keys_provider=default_keys_provider,
        require_kid=False,
    )

    await _valid_tokens_scenario(validator, include_headers=False)


@pytest.mark.asyncio
async def test_jwt_validator_raises_for_invalid_issuer(default_keys_provider):
    validator = JWTValidator(
        valid_audiences=["a"], valid_issuers=["b"], keys_provider=default_keys_provider
    )

    payload = {"aud": "a", "iss": "NO"}
    valid_token = get_access_token("0", payload)

    with pytest.raises(InvalidAccessToken):
        await validator.validate_jwt(valid_token)


@pytest.mark.asyncio
async def test_jwt_validator_raises_for_invalid_audience(default_keys_provider):
    validator = JWTValidator(
        valid_audiences=["a"], valid_issuers=["b"], keys_provider=default_keys_provider
    )

    payload = {"aud": "NO", "iss": "b"}
    valid_token = get_access_token("0", payload)

    with pytest.raises(InvalidAccessToken):
        await validator.validate_jwt(valid_token)


def test_authority_keys_provider_raises_for_missing_parameter():
    with pytest.raises(TypeError):
        AuthorityKeysProvider(None)  # type: ignore

    with pytest.raises(TypeError):
        AuthorityKeysProvider("")


def test_url_keys_provider_raises_for_missing_parameter():
    with pytest.raises(TypeError):
        URLKeysProvider(None)  # type: ignore

    with pytest.raises(TypeError):
        URLKeysProvider("")


def test_caching_keys_provider_raises_for_missing_parameter():
    with pytest.raises(TypeError):
        CachingKeysProvider(None, 1)  # type: ignore
