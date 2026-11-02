"""Source-aware education exclusions, applied before repository result limits."""
def training_exclusions(values):
    if not isinstance(values,(list,tuple)) or len(values)>1000:raise ValueError('Invalid training exclusions')
    result=[]
    for value in values:
        if not isinstance(value,str) or ':' not in value:raise ValueError('Invalid training exclusion')
        source,identity=value.split(':',1)
        if source not in {'boottent','goyong24_training'} or not 1<=len(identity)<=128:
            raise ValueError('Invalid training exclusion')
        result.append((source,identity))
    return list(dict.fromkeys(result))


def training_mode(value):
    if value not in (None,'online','offline'):raise ValueError('Invalid delivery mode')
    return value
