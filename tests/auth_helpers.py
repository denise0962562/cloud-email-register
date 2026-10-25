"""Exercise the real login/CSRF flow for existing authenticated workflow tests."""
import web_ui


def admin_client():
    store = web_ui.app.extensions['admin_auth']
    with store.connect() as db:
        exists = db.execute('SELECT 1 FROM admin').fetchone()
    if not exists:
        store.create_admin('workflow-admin', 'workflow-password-123456')
    client = web_ui.app.test_client()
    response = client.post('/api/auth/login', json={
        'username':'workflow-admin', 'password':'workflow-password-123456'})
    assert response.status_code == 200
    client.environ_base['HTTP_X_CSRF_TOKEN'] = response.json['csrf_token']
    return client
