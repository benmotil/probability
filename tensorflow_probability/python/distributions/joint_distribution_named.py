# Copyright 2018 The TensorFlow Probability Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ============================================================================
"""The `JointDistributionNamed` class."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from tensorflow_probability.python.distributions import joint_distribution_sequential
from tensorflow_probability.python.internal import distribution_util

__all__ = [
    'JointDistributionNamed',
]


class JointDistributionNamed(
    joint_distribution_sequential.JointDistributionSequential):
  """Joint distribution parameterized by named distribution-making functions.

  This distribution enables both sampling and joint probability computation from
  a single model specification.

  A joint distribution is a collection of possibly interdependent distributions.
  Like `JointDistributionSequential`, `JointDistributionNamed` is parameterized
  by several distribution-making functions. Unlike `JointDistributionNamed`,
  each distribution-making function must have its own key. Additionally every
  distribution-making function's arguments must refer to only specified keys.

  #### Mathematical Details

  Internally `JointDistributionNamed` implements the chain rule of probability.
  That is, the probability function of a length-`d` vector `x` is,

  ```none
  p(x) = prod{ p(x[i] | x[:i]) : i = 0, ..., (d - 1) }
  ```

  The `JointDistributionNamed` is parameterized by a `dict` (or `namedtuple`)
  composed of either:

  1. `tfp.distributions.Distribution`-like instances or,
  2. `callable`s which return a `tfp.distributions.Distribution`-like instance.

  The "conditioned on" elements are represented by the `callable`'s required
  arguments; every argument must correspond to a key in the named
  distribution-making functions. Distribution-makers which are directly a
  `Distribution`-like instance are allowed for convenience and semantically
  identical a zero argument `callable`. When the maker takes no arguments it is
  preferable to directly provide the distribution instance.

  #### Examples

  ```python
  tfd = tfp.distributions

  # Consider the following generative model:
  #     e ~ Exponential(rate=[100,120])
  #     g ~ Gamma(concentration=e[0], rate=e[1])
  #     n ~ Normal(loc=0, scale=2.)
  #     m ~ Normal(loc=n, scale=g)
  #     for i = 1, ..., 12:
  #       x[i] ~ Bernoulli(logits=m)

  # In TFP, we can write this as:
  joint = tfd.JointDistributionNamed(dict(
      e=             tfd.Independent(tfd.Exponential(rate=[100, 120]), 1),
      g=lambda    e: tfd.Gamma(concentration=e[..., 0], rate=e[..., 1]),
      n=             tfd.Normal(loc=0, scale=2.),
      m=lambda n, g: tfd.Normal(loc=n, scale=g),
      x=lambda    m: tfd.Sample(tfd.Bernoulli(logits=m), 12),
  ))
  # Notice the 1:1 correspondence between "math" and "code". Further, notice
  # that unlike `JointDistributionSequential`, there is no need to put the
  # distribution-making functions in topologically sorted order nor is it ever
  # necessary to use dummy arguments to skip dependencies.

  x = joint.sample()
  # ==> A 5-element `dict` of tfd.Distribution instances.
  joint.log_prob(x)
  # ==> A scalar `Tensor` representing the total log prob under all five
  #     distributions.

  joint._resolve_graph()
  # ==> (('e', ()),
  #      ('g', ('e',)),
  #      ('n', ()),
  #      ('m', ('n', 'g')),
  #      ('x', ('m',)))
  ```

  #### Discussion

  `JointDistributionNamed` topologically sorts the distribution-making functions
  and calls each by feeding in all previously created dependencies. A
  distribution-maker must either be a:

  1. `tfd.Distribution`-like instance (e.g., `e` and `n` in the above example),
  2. Python `callable` (e.g., `g`, `m`, `x` in the above example).

  Regarding #1, an object is deemed "`tfd.Distribution`-like" if it has a
  `sample`, `log_prob`, and distribution properties, e.g., `batch_shape`,
  `event_shape`, `dtype`.

  Regarding #2, in addition to using a function (or `lambda`), supplying a TFD
  "`class`" is also permissible, this also being a "Python `callable`." For
  example, instead of writing:
  `lambda loc, scale: tfd.Normal(loc=loc, scale=scale)`
  one could have simply written `tfd.Normal`.

  Notice that directly providing a `tfd.Distribution`-like instance means there
  cannot exist a (dynamic) dependency on other distributions; it is
  "independent" both "computationally" and "statistically." The same is
  self-evidently true of zero-argument `callable`s.

  A distribution instance depends on other distribution instances through the
  distribution making function's *required arguments*. The distribution makers'
  arguments are parameterized by samples from the corresponding previously
  constructed distributions. ("Previous" in the sense of a topological sorting
  of dependencies.)

  **Note**: unlike other non-`JointDistribution` distributions in
  `tfp.distributions`, `JointDistribution.sample` (and subclasses) return a
  structure of  `Tensor`s rather than a `Tensor`.  A structure can be a `list`,
  `tuple`, `dict`, `collections.namedtuple`, etc. Accordingly
  `joint.batch_shape` returns a structure of `TensorShape`s for each of the
  distributions' batch shapes and `joint.batch_shape_tensor()` returns a
  structure of `Tensor`s for each of the distributions' event shapes. (Same with
  `event_shape` analogues.)
  """

  def __init__(self, model, validate_args=False, name=None):
    """Construct the `JointDistributionNamed` distribution.

    Args:
      model: Python `dict` or `namedtuple` of distribution-making functions each
        with required args corresponding only to other keys in the `dict`.
      validate_args: Python `bool`.  Whether to validate input with asserts.
        If `validate_args` is `False`, and the inputs are invalid,
        correct behavior is not guaranteed.
      name: The name for ops managed by the distribution.
        Default value: `"JointDistributionNamed"`.
    """
    super(JointDistributionNamed, self).__init__(
        model, validate_args, name or 'JointDistributionNamed')

  def _build(self, model):
    """Creates `dist_fn`, `dist_fn_wrapped`, `dist_fn_args`, `dist_fn_name`."""
    [
        self._dist_fn,
        self._dist_fn_wrapped,
        self._dist_fn_args,
        self._dist_fn_name,  # JointDistributionSequential doesn't have this.
    ] = _prob_chain_rule_flatten(model)

  def _unflatten(self, xs):
    kwargs = dict(zip(self._dist_fn_name, tuple(xs)))
    return type(self._original_model)(**kwargs)

  def _flatten(self, xs):
    if xs is None:
      return (None,) * len(self._dist_fn_name)
    if hasattr(xs, 'get'):
      return tuple(xs.get(n, None) for n in self._dist_fn_name)
    return tuple(getattr(xs, n) for n in self._dist_fn_name)


class _Node(object):

  def __init__(self, name, parents):
    self.name = name
    self.parents = parents
    self.depth = -1


def _depth(g):
  """Computes the number of edges on longest path from node to root."""
  def _explore(v):
    if v.depth < 0:
      v.depth = ((1 + max([-1] + [_explore(annotated_graph[u])
                                  for u in v.parents]))
                 if v.parents else 0)
    return v.depth
  annotated_graph = {k: _Node(k, v) for k, v in g.items()}
  for v in annotated_graph.values():
    _explore(v)
  return annotated_graph


def _best_order(g):
  """Creates tuple of str tuple-str pairs representing resolved & sorted DAG."""
  def _explore(u):
    """Recursive function to ascend up through unvisited dependencies."""
    if u.depth < 0:
      return  # Already visited.
    if not u.parents:
      result.append((u.name, u.parents))
      u.depth = -1  # Mark visited.
      return
    b = (u.name, [])
    result.append(b)
    u.depth = -1  # Mark visited.
    d = 0
    for v in sorted((g.get(p) for p in u.parents), key=lambda v: v.depth):
      n0 = len(result)
      _explore(v)
      n1 = len(result)
      b[1].extend(['_']*d + [v.name])
      d = n1 - n0 - 1
  g = _depth(g)
  result = []
  for u in sorted(g.values(), key=lambda v: v.depth, reverse=True):
    _explore(u)
  return tuple(reversed(result))


def _prob_chain_rule_flatten(named_makers):
  """Creates lists of callables suitable for JDSeq."""
  def _make(dist_fn, args):
    if args is None:
      return lambda *_: dist_fn
    if not args:
      return lambda *_: dist_fn()
    def _fn(*xs):
      kwargs = dict(zip(args, reversed(xs[-len(args):])))
      kwargs.pop('_', None)
      return dist_fn(**kwargs)
    return _fn
  named_makers = (named_makers._asdict()
                  if hasattr(named_makers, '_asdict')
                  else dict(named_makers))
  g = {k: (None if distribution_util.is_distribution_instance(v)
           else joint_distribution_sequential._get_required_args(v))  # pylint: disable=protected-access
       for k, v in named_makers.items()}
  g = _best_order(g)
  dist_fn_name, dist_fn_args = zip(*g)
  dist_fn_args = tuple(None if a is None else tuple(a) for a in dist_fn_args)
  dist_fn_wrapped = tuple(_make(named_makers[name], parents)
                          for (name, parents) in g)
  dist_fn = tuple(named_makers.get(n) for n in dist_fn_name)
  return dist_fn, dist_fn_wrapped, dist_fn_args, dist_fn_name
