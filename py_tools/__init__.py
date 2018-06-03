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


def repr_object(x, posAttributeNames=None, kwAttributeNames=None):
    '''
    Builds a string representation of an object using a format representing object initialization.

    @param x                 any
    @param posAttributeNames None or iter(str); iterable of attribute names for positional arguments
    @param kwAttributeNames  None or mapping(str: str) or iter(str); mapping of argument name to attribute name for
                             keyword arguments or iterable of attribute names
    @return str
    '''
    import collections

    args = []

    if posAttributeNames is not None:
        for attributeName in posAttributeNames:
            value = getattr(x, attributeName)
            args.append(repr(value))

    if kwAttributeNames is not None:
        if not isinstance(kwAttributeNames, collections.Mapping):
            kwAttributeNames = collections.OrderedDict((''.join([attributeName[0].lower(), attributeName[1:]]),
                                                        attributeName) for attributeName in kwAttributeNames)

        for argumentName, attributeName in kwAttributeNames.items():
            value = getattr(x, attributeName)
            args.append('{}={}'.format(argumentName, repr(value)))

    r = '{}({})'.format(type(x).__name__, ', '.join(args))
    return r
