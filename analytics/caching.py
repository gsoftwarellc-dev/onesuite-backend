"""
Analytics Caching
Redis-backed caching for dashboard and metrics endpoints.
"""
import hashlib
import json
import logging
from functools import wraps
from typing import Any, Optional, Callable

from django.core.cache import cache
from django.conf import settings

logger = logging.getLogger(__name__)

# Cache TTL in seconds
DASHBOARD_CACHE_TTL = 300  # 5 minutes
METRICS_CACHE_TTL = 300    # 5 minutes


def _hash_params(params: dict) -> str:
    """Create a deterministic hash of query parameters."""
    sorted_items = sorted(params.items())
    params_str = json.dumps(sorted_items, sort_keys=True, default=str)
    return hashlib.md5(params_str.encode()).hexdigest()[:12]


def build_dashboard_cache_key(dashboard_type: str, user_id: int, **params) -> str:
    """
    Build cache key for dashboard endpoints.
    Key: dashboard:{role}:{user_id}:{params_hash}
    """
    params_hash = _hash_params(params)
    return f"analytics:dashboard:{dashboard_type}:{user_id}:{params_hash}"


def build_metrics_cache_key(model: str, **params) -> str:
    """
    Build cache key for metrics endpoints.
    Key: metrics:{model}:{params_hash}
    """
    params_hash = _hash_params(params)
    return f"analytics:metrics:{model}:{params_hash}"


def build_top_performers_cache_key(scope: str, scope_id: Optional[int], period: str) -> str:
    """
    Build cache key for top performers endpoint.
    Key: top:{scope}:{scope_id}:{period}
    """
    scope_id_str = str(scope_id) if scope_id else 'global'
    return f"analytics:top:{scope}:{scope_id_str}:{period}"


def build_trend_cache_key(model: str, scope: str, scope_id: Optional[int], months: int) -> str:
    """
    Build cache key for trend endpoints.
    Key: trend:{model}:{scope}:{scope_id}:{months}
    """
    scope_id_str = str(scope_id) if scope_id else 'global'
    return f"analytics:trend:{model}:{scope}:{scope_id_str}:{months}"


def get_cached(key: str) -> Optional[Any]:
    """Get value from cache if available."""
    try:
        return cache.get(key)
    except Exception as e:
        logger.warning(f"Cache get error for {key}: {e}")
        return None


def set_cached(key: str, value: Any, ttl: int = DASHBOARD_CACHE_TTL):
    """Set value in cache with TTL."""
    try:
        cache.set(key, value, ttl)
    except Exception as e:
        logger.warning(f"Cache set error for {key}: {e}")


def delete_cached(key: str):
    """Delete value from cache."""
    try:
        cache.delete(key)
    except Exception as e:
        logger.warning(f"Cache delete error for {key}: {e}")


def cached_view(cache_key_builder: Callable, ttl: int = DASHBOARD_CACHE_TTL):
    """
    Decorator for caching view responses.
    
    Usage:
        @cached_view(lambda request, **kwargs: build_dashboard_cache_key('finance', request.user.id, **request.query_params.dict()))
        def get(self, request):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, request, *args, **kwargs):
            # Build cache key
            try:
                cache_key = cache_key_builder(request, **kwargs)
            except Exception as e:
                logger.warning(f"Cache key build error: {e}")
                return func(self, request, *args, **kwargs)
            
            # Try to get from cache
            cached_response = get_cached(cache_key)
            if cached_response is not None:
                logger.debug(f"Cache HIT: {cache_key}")
                from rest_framework.response import Response
                return Response(cached_response)
            
            logger.debug(f"Cache MISS: {cache_key}")
            
            # Call the actual view
            response = func(self, request, *args, **kwargs)
            
            # Cache successful responses
            if response.status_code == 200:
                set_cached(cache_key, response.data, ttl)
            
            return response
        return wrapper
    return decorator


class CacheMiddleware:
    """
    Optional middleware for analytics caching.
    Not used by default - caching is handled per-view.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        return self.get_response(request)
