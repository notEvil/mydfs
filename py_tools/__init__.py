class cached:
    '''
    Decorator which adds the argument cache, builds keys from arguments and retrieves results from cache or stores
    results in cache.
    '''

    def __init__(self, argIdcs=None, kwargNames=None):
        '''
        @param argIdcs    None or collection(int); collection of indices of positional arguments
        @param kwargNames None or collection(str); collection of names of keyword arguments
        '''
        self.ArgIdcs = argIdcs
        self.KwargNames = kwargNames

    def __call__(self, function):
        def _cached(*args, cache=None, **kwargs):
            if cache is None:
                r = function(*args, **kwargs)
                return r

            key = []
            key.extend(args if self.ArgIdcs is None else (args[i] for i in self.ArgIdcs))
            key.extend(
                sorted(kwargs.items()) if self.KwargNames is None else (kwargs[name] for name in self.KwargNames))
            key = tuple(key)

            try:
                r = cache.get(key, None)

            except TypeError:
                r = function(*args, **kwargs)
                return r

            if r is not None:
                return r

            cache[key] = r = function(*args, **kwargs)
            return r

        return _cached
