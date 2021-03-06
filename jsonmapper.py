# -*- coding: utf-8 -*-
#
# Copyright (C) 2007-2009 Christopher Lenz
# Copyright (C) 2011 Matthew Good
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.

"""Mapping from raw JSON data structures to Python objects and vice versa.

To define a document mapping, you declare a Python class inherited from
`Mapping`, and add any number of `Field` attributes:

>>> from jsonmapper import Mapping, TextField, IntegerField, DateTimeField
>>> class Person(Mapping):
...     name = TextField()
...     age = IntegerField()
...     added = DateTimeField(default=datetime.now)
>>> person = Person.from_kwargs(name='John Doe', age=42)
>>> person #doctest: +ELLIPSIS
<Person ...>
>>> person.age
42

"""
import collections
import copy
import sys
from abc import ABCMeta
from calendar import timegm
from datetime import date, datetime, time
from decimal import Decimal
from time import strptime, struct_time

__all__ = ['Mapping', 'Field', 'TextField', 'FloatField',
           'IntegerField', 'LongField', 'BooleanField', 'DecimalField',
           'DateField', 'DateTimeField', 'TimeField', 'DictField', 'ListField',
           'TypedField',
           ]
__docformat__ = 'restructuredtext en'

# Python 2/3 compatibility helpers. These helpers are used internally and are
# not exported.
_METACLASS_ = '_metaclass_helper_'


def with_metaclass(meta, base=object):
    return meta(_METACLASS_, (base,), {})


PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] == 3

if PY3:
    unicode_type = str
    string_type = bytes
    basestring = str
    long = int
elif PY2:
    unicode_type = unicode
    string_type = basestring
else:
    raise RuntimeError('Unsupported python version.')


class Field(object):
    """Basic unit for mapping a piece of data between Python and JSON.

    Instances of this class can be added to subclasses of `Mapping` to describe
    the mapping of a document.
    """

    def __init__(self, name=None, default=None):
        self.name = name
        self.default = default

    def __get__(self, instance, owner):
        if instance is None:
            return self
        value = instance.get(self.name)
        if value is not None:
            value = self._to_python(value)
        elif self.default is not None:
            default = self.default
            if callable(default):
                default = default()
            value = default
        return value

    def __set__(self, instance, value):
        if value is not None:
            value = self._to_json(value)
        instance[self.name] = value

    def _to_python(self, value):
        return unicode_type(value)

    def _to_json(self, value):
        return self._to_python(value)


class MappingMeta(ABCMeta):
    # noinspection PyInitNewSignature
    def __new__(mcs, name, bases, dct):
        fields = {}
        for base in bases:
            base_fields = getattr(base, '_fields', {})
            fields.update(base_fields)
        for field_name, field_value in dct.items():
            if isinstance(field_value, Field):
                if not field_value.name:
                    field_value.name = field_name
                fields[field_name] = field_value

        cls = super(MappingMeta, mcs).__new__(mcs, name, bases, dct)
        cls._fields = fields
        return cls


class Mapping(with_metaclass(MappingMeta), collections.MutableMapping):
    def __init__(self, values=None):
        values = values or dict()
        self._data = {}
        for field_name, field in self._fields.items():
            if field_name in values:
                setattr(self, field_name, values.pop(field_name))
            else:
                setattr(self, field_name, getattr(self, field_name))

    def __repr__(self):
        return '<%s %r>' % (type(self).__name__, self._data)

    def __getitem__(self, name):
        return self._data[name]

    def __setitem__(self, name, value):
        self._data[name] = value

    def __delitem__(self, name):
        del self._data[name]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data or ())

    def unwrap(self):
        return self._data

    @classmethod
    def build(cls, **d):
        fields = {}
        for attrname, attrval in d.items():
            if not attrval.name:
                attrval.name = attrname
            fields[attrname] = attrval
        d['_fields'] = fields
        return type('AnonymousStruct', (cls,), d)

    @classmethod
    def from_kwargs(cls, **values):
        return cls(values=values)


class TextField(Field):
    """Mapping field for string values."""
    _to_python = unicode_type


class FloatField(Field):
    """Mapping field for float values."""
    _to_python = float


class IntegerField(Field):
    """Mapping field for integer values."""
    _to_python = int


class LongField(Field):
    """Mapping field for long integer values."""
    _to_python = long


class BooleanField(Field):
    """Mapping field for boolean values."""
    _to_python = bool


class DecimalField(Field):
    """Mapping field for decimal values."""

    def _to_python(self, value):
        return Decimal(value)

    def _to_json(self, value):
        return unicode_type(value)


class DateField(Field):
    """Mapping field for storing dates.

    >>> field = DateField()
    >>> field._to_python('2007-04-01')
    datetime.date(2007, 4, 1)
    >>> field._to_json(date(2007, 4, 1))
    '2007-04-01'
    >>> field._to_json(datetime(2007, 4, 1, 15, 30))
    '2007-04-01'
    """

    def _to_python(self, value):
        if isinstance(value, basestring):
            try:
                value = date(*strptime(value, '%Y-%m-%d')[:3])
            except ValueError:
                raise ValueError('Invalid ISO date %r' % value)
        return value

    def _to_json(self, value):
        if isinstance(value, datetime):
            value = value.date()
        return value.isoformat()


class DateTimeField(Field):
    """Mapping field for storing date/time values.

    >>> field = DateTimeField()
    >>> field._to_python('2007-04-01T15:30:00Z')
    datetime.datetime(2007, 4, 1, 15, 30)
    >>> field._to_json(datetime(2007, 4, 1, 15, 30, 0, 9876))
    '2007-04-01T15:30:00Z'
    >>> field._to_json(date(2007, 4, 1))
    '2007-04-01T00:00:00Z'
    """

    def _to_python(self, value):
        if isinstance(value, basestring):
            try:
                value = value.split('.', 1)[0]  # strip out microseconds
                value = value.rstrip('Z')  # remove timezone separator
                value = datetime(*strptime(value, '%Y-%m-%dT%H:%M:%S')[:6])
            except ValueError:
                raise ValueError('Invalid ISO date/time %r' % value)
        return value

    def _to_json(self, value):
        if isinstance(value, basestring):
            value = self._to_python(value)

        if isinstance(value, struct_time):
            value = datetime.utcfromtimestamp(timegm(value))
        elif not isinstance(value, datetime):
            value = datetime.combine(value, time(0))
        return value.replace(microsecond=0).isoformat() + 'Z'


class TimeField(Field):
    """Mapping field for storing times.

    >>> field = TimeField()
    >>> field._to_python('15:30:00')
    datetime.time(15, 30)
    >>> field._to_json(time(15, 30))
    '15:30:00'
    >>> field._to_json(datetime(2007, 4, 1, 15, 30))
    '15:30:00'
    """

    def _to_python(self, value):
        if isinstance(value, basestring):
            try:
                value = value.split('.', 1)[0]  # strip out microseconds
                value = time(*strptime(value, '%H:%M:%S')[3:6])
            except ValueError:
                raise ValueError('Invalid ISO time %r' % value)
        return value

    def _to_json(self, value):
        if isinstance(value, datetime):
            value = value.time()
        return value.replace(microsecond=0).isoformat()


class DictField(Field):
    """Field type for nested dictionaries.

    >>> class Post(Mapping):
    ...     title = TextField()
    ...     content = TextField()
    ...     author = DictField(Mapping.build(
    ...         name = TextField(),
    ...         email = TextField()
    ...     ))
    ...     extra = DictField()

    >>> post = Post.from_kwargs(
    ...     title='Foo bar',
    ...     author=dict(name='John Doe',
    ...                 email='john@doe.com'),
    ...     extra=dict(foo='bar'),
    ... )
    >>> post #doctest: +ELLIPSIS
    <Post ...>
    >>> post.author.name
    u'John Doe'
    >>> post.author.email
    u'john@doe.com'
    >>> post.extra
    {'foo': 'bar'}

    >>> class Blog(Mapping):
    ...   post = DictField(Post)

    >>> blog = Blog({'post': {'title': 'Foo', 'author': {'name': 'Jane Doe', 'email': 'jane@doe.com'}, 'extra': {}}})
    >>> blog.post.title
    u'Foo'

    >>> blog = Blog.from_kwargs(post=post)
    >>> blog.post.author.name
    u'John Doe'

    """

    def __init__(self, mapping=None, name=None, default=None):
        default = default or {}
        Field.__init__(self, name=name, default=lambda: default.copy())
        self.mapping = mapping

    def _to_python(self, value):
        if self.mapping is None:
            return value
        else:
            return self.mapping.from_kwargs(**value)

    def _to_json(self, value):
        if self.mapping is None:
            return value
        if not isinstance(value, Mapping):
            value = self.mapping.from_kwargs(**value)
        return value.unwrap()


class ListField(Field):
    """Field type for sequences of other fields.

    >>> class Post(Mapping):
    ...     title = TextField()
    ...     content = TextField()
    ...     pubdate = DateTimeField(default=datetime.now)
    ...     comments = ListField(DictField(Mapping.build(
    ...         author = TextField(),
    ...         content = TextField(),
    ...         time = DateTimeField()
    ...     )))

    >>> post = Post.from_kwargs(title='Foo bar')
    >>> post.comments.append(author='myself', content='Bla bla',
    ...                      time=datetime.now())
    >>> len(post.comments)
    1
    >>> post #doctest: +ELLIPSIS
    <Post ...>
    >>> comment = post.comments[0]
    >>> comment['author']
    u'myself'
    >>> comment['content']
    u'Bla bla'
    >>> comment['time'] #doctest: +ELLIPSIS
    '...T...Z'

    """

    def __init__(self, field, name=None, default=None):
        default = default or []
        Field.__init__(self, name=name, default=lambda: copy.copy(default))
        if type(field) is type:
            if issubclass(field, Field):
                field = field()
            elif issubclass(field, Mapping):
                field = DictField(field)
        self.field = field

    def _to_python(self, value):
        return self.Proxy(value, self.field)

    def _to_json(self, value):
        return [self.field._to_json(item) for item in value]

    class Proxy(object):

        def __init__(self, list_, field):
            self.list = list_
            self.field = field

        def __lt__(self, other):
            return self.list < other

        def __le__(self, other):
            return self.list <= other

        def __eq__(self, other):
            return self.list == other

        def __ne__(self, other):
            return self.list != other

        def __gt__(self, other):
            return self.list > other

        def __ge__(self, other):
            return self.list >= other

        def __repr__(self):
            return repr(self.list)

        def __str__(self):
            return str(self.list)

        def __unicode__(self):
            return unicode_type(self.list)

        def __delitem__(self, index):
            del self.list[index]

        def __getitem__(self, index):
            return self.field._to_python(self.list[index])

        def __setitem__(self, index, value):
            self.list[index] = self.field._to_json(value)

        def __delslice__(self, i, j):
            del self.list[i:j]

        def __getslice__(self, i, j):
            return ListField.Proxy(self.list[i:j], self.field)

        def __setslice__(self, i, j, seq):
            self.list[i:j] = (self.field._to_json(v) for v in seq)

        def __contains__(self, value):
            for item in self.list:
                if self.field._to_python(item) == value:
                    return True
            return False

        def __iter__(self):
            for index in range(len(self)):
                yield self[index]

        def __len__(self):
            return len(self.list)

        def __nonzero__(self):
            return bool(self.list)

        def append(self, *args, **kwargs):
            if args or not isinstance(self.field, DictField):
                if len(args) != 1:
                    raise TypeError('append() takes exactly one argument '
                                    '(%s given)' % len(args))
                value = args[0]
            else:
                value = kwargs
            self.list.append(self.field._to_json(value))

        def count(self, value):
            return [i for i in self].count(value)

        def extend(self, list):
            for item in list:
                self.append(item)

        def index(self, value):
            return self.list.index(self.field._to_json(value))

        def insert(self, idx, *args, **kwargs):
            if args or not isinstance(self.field, DictField):
                if len(args) != 1:
                    raise TypeError('insert() takes exactly 2 arguments '
                                    '(%s given)' % len(args))
                value = args[0]
            else:
                value = kwargs
            self.list.insert(idx, self.field._to_json(value))

        def remove(self, value):
            return self.list.remove(self.field._to_json(value))

        def pop(self, *args):
            return self.field._to_python(self.list.pop(*args))
