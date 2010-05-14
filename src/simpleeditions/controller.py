# -*- coding: utf-8 -*-
#
# Copyright © 2010 Jonatan Littke
#
# This file is part of SimpleEditions.
#
# SimpleEditions is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.
#
# SimpleEditions is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License along with
# SimpleEditions. If not, see http://www.gnu.org/licenses/.
#

"""A set of functions that control the application.

The purpose of this module is to provide a bridge between the user (through
views) and the back-end (models and data logic).

"""

from datetime import datetime, timedelta
import os

from google.appengine.api import memcache

import simpleeditions
from simpleeditions import model, utils
from simpleeditions.utils import public

def get_article_dict(article, include_content=False):
    props = ['key.id', ('_entity.user.id', 'user_id'), 'user_name', 'created',
             'last_modified', 'edits', 'views', 'slug', 'title']
    if include_content:
        props += ['content', 'html']
    return utils.get_dict(article, props)

def get_current_user(handler):
    try:
        session_id = handler.request.cookies['session']
        return model.User.get_session(session_id)
    except KeyError:
        return None

def get_user_dict(user, include_private_values=False):
    props = ['key.id', 'display_name', 'created', 'status']
    if include_private_values:
        props += ['email']
    return utils.get_dict(user, props)

def start_user_session(handler, user):
    user.start_session()
    utils.set_cookie(handler, 'session', user.session, user.expires)

@public
def create_article(handler, title, content):
    user = get_current_user(handler)
    if not user:
        raise simpleeditions.NotLoggedInError(
            'You must be logged in to create an article.')
    article = model.Article.create(user, title, content)

    return get_article_dict(article)

@public
def get_article(handler, id):
    article = model.Article.get_by_id(id)
    if not article:
        raise simpleeditions.ArticleNotFoundError(
            'Could not find article with id %r.' % id)

    # memcache key used for counting views.
    views_key = 'article:%d:views' % id

    # Don't increment views if user has article id in cookie.
    try:
        cookie = handler.request.cookies['articles']
    except KeyError:
        cookie = ':'
    if not (':%d:' % id) in cookie:
        cookie += ('%d:' % id)
        utils.set_cookie(handler, 'articles', cookie,
                         datetime.now() + timedelta(days=7))

        # Id was not in cookie, increment by one if IP has not incremented
        # 5 or more times before.
        ip_key = 'article:%d:views:%s' % (id, os.environ['REMOTE_ADDR'])
        if memcache.get(ip_key) < 5:
            memcache.incr(ip_key, initial_value=0)
            cached_views = memcache.incr(views_key, initial_value=0) or 0L
        else:
            cached_views = long(memcache.get(views_key) or 0)
    else:
        cached_views = long(memcache.get(views_key) or 0)

    # Aggregate stored views with cached views.
    article.views += cached_views

    # Store views to entity once per hour and reset the cache counter.
    if datetime.now() - article.last_save > timedelta(hours=1):
        article.put()
        memcache.delete(views_key)

    return get_article_dict(article, True)

@public
def get_articles(handler, order, limit, include_content=False):
    articles = model.Article.all().order(order).fetch(limit)
    return [get_article_dict(article, include_content) for article in articles]

@public
def get_login_url(handler, auth_type, return_url='/'):
    try:
        auth_class = model.AUTH_TYPES[auth_type]
    except KeyError:
        raise ValueError('Invalid authentication type.')

    return auth_class.get_login_url(return_url)

@public
def get_user_info(handler, id=None):
    """Returns information about a user. The current user is returned if no id
    is specified.

    """
    if id:
        user = model.User.get_by_id(id)
        if not user:
            raise simpleeditions.UserNotFoundError(
                'Could not find user with id %r.' % id)
        return get_user_dict(user)
    else:
        user = get_current_user(handler)
        if user:
            return get_user_dict(user, True)

@public
def log_in(handler, auth_type, *args, **kwargs):
    try:
        auth_class = model.AUTH_TYPES[auth_type]
    except KeyError:
        raise ValueError('Invalid authentication type.')

    auth = auth_class.log_in(*args, **kwargs)
    user = auth.user

    # Start a session and create a session cookie.
    start_user_session(handler, user)

    return get_user_dict(user, True)

@public
def log_out(handler):
    user = get_current_user(handler)
    if user:
        user.end_session()

        # Empty session cookie and force it to expire.
        utils.set_cookie(handler, 'session', '', datetime(1987, 7, 31, 3, 42))

@public
def register(handler, auth_type, *args, **kwargs):
    try:
        auth_class = model.AUTH_TYPES[auth_type]
    except KeyError:
        raise ValueError('Invalid authentication type.')

    auth = auth_class.register(*args, **kwargs)
    start_user_session(handler, auth.user)
    return get_user_dict(auth.user, True)

@public
def update_article(handler, id, title=None, content=None, message=''):
    if not isinstance(id, int):
        raise TypeError('Article id must be an integer.')

    user = get_current_user(handler)
    if not user:
        raise simpleeditions.NotLoggedInError(
            'You must be logged in to update an article.')

    article = model.Article.update(id, user, title, content, message)
    return get_article_dict(article)
