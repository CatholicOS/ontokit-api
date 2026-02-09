#!/usr/bin/env python3
"""
Setup script for Zitadel - creates project and applications for Axigraph.

Run this after Zitadel is up and running:
    python scripts/setup-zitadel.py

Prerequisites:
    pip install httpx
"""

import json
import sys
import time

import httpx

ZITADEL_URL = "http://localhost:8080"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "Admin123!"

# Application redirect URIs
WEB_REDIRECT_URIS = [
    "http://localhost:3000/api/auth/callback/zitadel",
    "http://localhost:3000",
]
WEB_LOGOUT_URIS = [
    "http://localhost:3000",
]


def wait_for_zitadel(max_attempts: int = 30) -> bool:
    """Wait for Zitadel to be ready."""
    print("Waiting for Zitadel to be ready...")
    for i in range(max_attempts):
        try:
            resp = httpx.get(f"{ZITADEL_URL}/debug/ready", timeout=5)
            if resp.status_code == 200:
                print("Zitadel is ready!")
                return True
        except httpx.HTTPError:
            pass
        print(f"  Attempt {i + 1}/{max_attempts}...")
        time.sleep(2)
    return False


def get_admin_token() -> str:
    """Get an admin access token from the PAT file created during Zitadel init."""
    print("Getting admin token...")

    # Try to get PAT from Docker volume
    import subprocess

    try:
        result = subprocess.run(
            ["docker", "cp", "axigraph-zitadel:/zitadel-data/admin.pat", "/tmp/admin.pat"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            with open("/tmp/admin.pat", "r") as f:
                pat = f.read().strip()
                if pat:
                    print("  Using PAT from Zitadel container")
                    return pat
    except Exception as e:
        print(f"  Could not get PAT from container: {e}")

    # Fallback: check environment variable
    import os
    pat = os.environ.get("ZITADEL_ADMIN_PAT")
    if pat:
        print("  Using PAT from environment variable")
        return pat

    print("ERROR: Could not get admin PAT.")
    print("You may need to create applications manually in Zitadel console.")
    print(f"Access Zitadel at: {ZITADEL_URL}")
    print(f"Login with: {ADMIN_USERNAME} / {ADMIN_PASSWORD}")
    sys.exit(1)


def create_project(client: httpx.Client, token: str) -> str:
    """Create the Axigraph project."""
    print("Creating Axigraph project...")

    resp = client.post(
        "/management/v1/projects",
        json={
            "name": "Axigraph",
            "projectRoleAssertion": False,  # Don't require role assertion in tokens
            "projectRoleCheck": False,  # Don't check user grants on login (simpler for dev)
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    if resp.status_code == 409:
        print("  Project already exists, fetching...")
        # List projects to find it
        list_resp = client.post(
            "/management/v1/projects/_search",
            json={"queries": [{"nameQuery": {"name": "Axigraph", "method": "TEXT_QUERY_METHOD_EQUALS"}}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        projects = list_resp.json().get("result", [])
        if projects:
            return projects[0]["id"]
        raise Exception("Could not find existing project")

    resp.raise_for_status()
    project_id = resp.json()["id"]
    print(f"  Created project: {project_id}")
    return project_id


def create_web_application(client: httpx.Client, token: str, project_id: str) -> dict:
    """Create the web application for Next.js frontend."""
    print("Creating web application...")

    resp = client.post(
        f"/management/v1/projects/{project_id}/apps/oidc",
        json={
            "name": "Axigraph Web",
            "redirectUris": WEB_REDIRECT_URIS,
            "postLogoutRedirectUris": WEB_LOGOUT_URIS,
            "responseTypes": ["OIDC_RESPONSE_TYPE_CODE"],
            "grantTypes": ["OIDC_GRANT_TYPE_AUTHORIZATION_CODE", "OIDC_GRANT_TYPE_REFRESH_TOKEN"],
            "appType": "OIDC_APP_TYPE_WEB",
            "authMethodType": "OIDC_AUTH_METHOD_TYPE_POST",
            "devMode": True,
            "accessTokenType": "OIDC_TOKEN_TYPE_JWT",
            "idTokenRoleAssertion": True,
            "idTokenUserinfoAssertion": True,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    if resp.status_code == 409:
        print("  Web application already exists")
        # Find existing app
        list_resp = client.get(
            f"/management/v1/projects/{project_id}/apps",
            headers={"Authorization": f"Bearer {token}"},
        )
        apps = list_resp.json().get("result", [])
        for app in apps:
            if app.get("name") == "Axigraph Web":
                return {"clientId": app.get("oidcConfig", {}).get("clientId")}
        return {}

    resp.raise_for_status()
    data = resp.json()
    print(f"  Created web app - Client ID: {data.get('clientId')}")
    return data


def create_native_application(client: httpx.Client, token: str, project_id: str) -> dict:
    """Create the native application for desktop clients (Device Flow)."""
    print("Creating native application for desktop clients...")

    resp = client.post(
        f"/management/v1/projects/{project_id}/apps/oidc",
        json={
            "name": "Axigraph Desktop",
            "redirectUris": ["http://localhost:8400/callback"],  # Local callback for desktop
            "responseTypes": ["OIDC_RESPONSE_TYPE_CODE"],
            "grantTypes": [
                "OIDC_GRANT_TYPE_AUTHORIZATION_CODE",
                "OIDC_GRANT_TYPE_REFRESH_TOKEN",
                "OIDC_GRANT_TYPE_DEVICE_CODE",
            ],
            "appType": "OIDC_APP_TYPE_NATIVE",
            "authMethodType": "OIDC_AUTH_METHOD_TYPE_NONE",  # Public client
            "devMode": True,
            "accessTokenType": "OIDC_TOKEN_TYPE_JWT",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    if resp.status_code == 409:
        print("  Native application already exists")
        list_resp = client.get(
            f"/management/v1/projects/{project_id}/apps",
            headers={"Authorization": f"Bearer {token}"},
        )
        apps = list_resp.json().get("result", [])
        for app in apps:
            if app.get("name") == "Axigraph Desktop":
                return {"clientId": app.get("oidcConfig", {}).get("clientId")}
        return {}

    resp.raise_for_status()
    data = resp.json()
    print(f"  Created native app - Client ID: {data.get('clientId')}")
    return data


def create_api_application(client: httpx.Client, token: str, project_id: str) -> dict:
    """Create the API application for backend-to-backend auth."""
    print("Creating API application...")

    resp = client.post(
        f"/management/v1/projects/{project_id}/apps/api",
        json={
            "name": "Axigraph API",
            "authMethodType": "API_AUTH_METHOD_TYPE_PRIVATE_KEY_JWT",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    if resp.status_code == 409:
        print("  API application already exists")
        return {}

    resp.raise_for_status()
    data = resp.json()
    print(f"  Created API app - Client ID: {data.get('clientId')}")
    return data


def main():
    """Main setup function."""
    print("=" * 60)
    print("Axigraph Zitadel Setup")
    print("=" * 60)

    # Wait for Zitadel
    if not wait_for_zitadel():
        print("ERROR: Zitadel is not ready after maximum attempts")
        sys.exit(1)

    # Get admin token
    try:
        token = get_admin_token()
    except Exception as e:
        print(f"\nCould not get admin token automatically: {e}")
        print("\nPlease set up Zitadel manually:")
        print(f"1. Open {ZITADEL_URL} in your browser")
        print(f"2. Login with: {ADMIN_USERNAME} / {ADMIN_PASSWORD}")
        print("3. Create a new project called 'Axigraph'")
        print("4. Create applications as described in the documentation")
        sys.exit(1)

    with httpx.Client(base_url=ZITADEL_URL, timeout=30) as client:
        # Create project
        project_id = create_project(client, token)

        # Create applications
        web_app = create_web_application(client, token, project_id)
        native_app = create_native_application(client, token, project_id)
        api_app = create_api_application(client, token, project_id)

    # Print configuration
    print("\n" + "=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    print("\nAdd these to your .env files:\n")

    print("# axigraph-api/.env")
    print(f"ZITADEL_ISSUER={ZITADEL_URL}")
    if native_app.get("clientId"):
        print(f"ZITADEL_CLIENT_ID={native_app['clientId']}")
    print()

    print("# axigraph-web/.env.local")
    print(f"ZITADEL_ISSUER={ZITADEL_URL}")
    if web_app.get("clientId"):
        print(f"ZITADEL_CLIENT_ID={web_app['clientId']}")
    if web_app.get("clientSecret"):
        print(f"ZITADEL_CLIENT_SECRET={web_app['clientSecret']}")
    print()

    print(f"Zitadel Console: {ZITADEL_URL}")
    print(f"Login: {ADMIN_USERNAME} / {ADMIN_PASSWORD}")


if __name__ == "__main__":
    main()
