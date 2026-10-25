"""Deny by default: administrator cookies for management, keys for public APIs."""
import os
import secrets
from pathlib import Path
from flask import request, jsonify, redirect, g
from admin_auth import AuthStore

COOKIE = 'hme_admin_session'
PUBLIC = {'/api/public/emails':'emails:read',
          '/api/public/inbox-links/export':'inbox-links:read',
          '/api/public/mail':'mail:read'}


def install_auth(app, root):
    app.extensions['admin_auth'] = AuthStore(Path(root)/'admin_auth.sqlite3')
    app.config.setdefault('ADMIN_SESSION_DAYS', int(os.environ.get('ADMIN_SESSION_DAYS', '30')))
    app.config.setdefault('AUTH_COOKIE_SECURE', os.environ.get('AUTH_COOKIE_SECURE','1') != '0')
    if not 1<=app.config['ADMIN_SESSION_DAYS']<=365:
        raise ValueError('ADMIN_SESSION_DAYS 必须为 1–365')

    def store():return app.extensions['admin_auth']

    @app.before_request
    def authorize():
        # Only code assets, the login screen and minimal liveness are anonymous.
        if (request.endpoint == 'static' and not request.path.endswith('.html')) or request.path in ['/login','/api/auth/login','/healthz']:
            if request.path == '/api/auth/login' and request.method == 'POST':
                origin = request.headers.get('Origin')
                if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
                    # Caddy terminates HTTPS; compare the explicit hostname as well.
                    from urllib.parse import urlsplit
                    parsed = urlsplit(origin)
                    if parsed.scheme!='https' or parsed.netloc!=request.host:
                        return jsonify(error='不允许跨站登录'),403
            return
        if request.path.startswith('/api/public/'):
            scope = PUBLIC.get(request.path)
            if not scope or request.method!='GET':return jsonify(error='公开 API 不存在'),404
            header = request.headers.get('Authorization','')
            token = header[7:] if header.startswith('Bearer ') else request.headers.get('X-API-Key','')
            scopes = store().key_scopes(token)
            if scopes is None:return jsonify(error='需要有效的 API Key'),401
            if scope not in scopes:return jsonify(error='API Key 缺少此接口权限'),403
            return
        token = request.cookies.get(COOKIE,'')
        g.admin_session = store().session(token)
        if not g.admin_session:
            if request.path.startswith('/api/'):return jsonify(error='请先登录管理员账号',login_required=True),401
            return redirect('/login')
        # Protected HTML is transformed below; never reuse a pre-auth cached panel.
        request.environ.pop('HTTP_IF_NONE_MATCH',None)
        request.environ.pop('HTTP_IF_MODIFIED_SINCE',None)
        if request.method not in ('GET','HEAD','OPTIONS'):
            supplied = request.headers.get('X-CSRF-Token','')
            if not secrets.compare_digest(supplied.encode(), g.admin_session['csrf_token'].encode()):
                return jsonify(error='会话请求校验失败，请刷新后重试'),403

    @app.after_request
    def protect_response(response):
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['X-Frame-Options']='SAMEORIGIN'
        if response.is_streamed and request.path.startswith('/api/') and g.get('admin_session'):
            original=response.response
            token=request.cookies.get(COOKIE,'')
            def checked_stream():
                try:
                    for chunk in original:
                        if not store().session(token):break
                        yield chunk
                finally:
                    if hasattr(original,'close'):original.close()
            response.response=checked_stream()
        if response.mimetype=='text/html' and g.get('admin_session'):
            response.direct_passthrough=False
            text=response.get_data(as_text=True)
            if '<head>' in text:response.set_data(text.replace('<head>','<head><script src="/static/admin_session.js"></script>',1))
        return response

    @app.get('/healthz')
    def auth_health():return jsonify(ok=True)

    @app.get('/login')
    def admin_login_page():return app.send_static_file('admin_login.html')

    @app.post('/api/auth/login')
    def admin_login():
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict):return jsonify(error='登录参数无效'),400
        try:result=store().login(data.get('username',''),data.get('password',''),request.remote_addr or '',app.config['ADMIN_SESSION_DAYS'])
        except ValueError as error:return jsonify(error=str(error)),429
        if not result:return jsonify(error='用户名或密码不正确'),401
        token,metadata=result
        old=request.cookies.get(COOKIE)
        if old:store().logout(old)
        response=jsonify(ok=True,**metadata)
        response.set_cookie(COOKIE,token,max_age=app.config['ADMIN_SESSION_DAYS']*86400,
                            secure=app.config['AUTH_COOKIE_SECURE'],httponly=True,samesite='Lax',path='/')
        return response

    @app.get('/api/auth/session')
    def admin_session():return jsonify(ok=True,**g.admin_session)

    @app.post('/api/auth/logout')
    def admin_logout():
        store().logout(request.cookies.get(COOKIE,''))
        response=jsonify(ok=True);response.delete_cookie(COOKIE,path='/');return response

    @app.post('/api/auth/password')
    def admin_password():
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict):return jsonify(error='参数无效'),400
        try:store().change_password(data.get('old_password'),data.get('new_password'))
        except ValueError as error:return jsonify(error=str(error)),400
        response=jsonify(ok=True);response.delete_cookie(COOKIE,path='/');return response

    @app.get('/admin/security')
    def admin_security():return app.send_static_file('admin_security.html')

    @app.route('/api/admin/api-keys',methods=['GET','POST'])
    def admin_api_keys():
        if request.method=='GET':return jsonify(keys=store().keys())
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict):return jsonify(error='参数无效'),400
        try:key_id,token=store().create_key(data.get('name'),data.get('scopes'))
        except ValueError as error:return jsonify(error=str(error)),400
        return jsonify(id=key_id,api_key=token),201

    @app.delete('/api/admin/api-keys/<key_id>')
    def admin_revoke_key(key_id):
        return (jsonify(ok=True),200) if store().revoke_key(key_id) else (jsonify(error='密钥不存在'),404)
