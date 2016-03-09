# Copyright 2014 The Oppia Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS-IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Jobs for statistics views."""

import ast
import collections

from core import jobs
from core.domain import stats_jobs_continuous
from core.platform import models
(base_models, stats_models, exp_models,) = models.Registry.import_models([
    models.NAMES.base_model, models.NAMES.statistics, models.NAMES.exploration
])
transaction_services = models.Registry.import_transaction_services()


class StatisticsAudit(jobs.BaseMapReduceJobManager):

    _STATE_COUNTER_ERROR_KEY = 'State Counter ERROR'

    @classmethod
    def entity_classes_to_map_over(cls):
        return [
            stats_models.ExplorationAnnotationsModel,
            stats_models.StateCounterModel]

    @staticmethod
    def map(item):
        if isinstance(item, stats_models.StateCounterModel):
            if item.first_entry_count < 0:
                yield (
                    StatisticsAudit._STATE_COUNTER_ERROR_KEY,
                    'Less than 0: %s %d' % (item.key, item.first_entry_count))
            return
        # Older versions of ExplorationAnnotations didn't store exp_id
        # This is short hand for making sure we get ones updated most recently
        else:
            if item.exploration_id is not None:
                yield (item.exploration_id, {
                    'version': item.version,
                    'starts': item.num_starts,
                    'completions': item.num_completions,
                    'state_hit': item.state_hit_counts
                })

    @staticmethod
    def reduce(key, stringified_values):
        if key == StatisticsAudit._STATE_COUNTER_ERROR_KEY:
            for value_str in stringified_values:
                yield (value_str,)
            return

        # If the code reaches this point, we are looking at values that
        # correspond to each version of a particular exploration.

        # These variables correspond to the VERSION_ALL version.
        all_starts = 0
        all_completions = 0
        all_state_hit = collections.defaultdict(int)

        # These variables correspond to the sum of counts for all other
        # versions besides VERSION_ALL.
        sum_starts = 0
        sum_completions = 0
        sum_state_hit = collections.defaultdict(int)

        for value_str in stringified_values:
            value = ast.literal_eval(value_str)
            if value['starts'] < 0:
                yield (
                    'Negative start count: exp_id:%s version:%s starts:%s' %
                    (key, value['version'], value['starts']),)

            if value['completions'] < 0:
                yield (
                    'Negative completion count: exp_id:%s version:%s '
                    'completions:%s' %
                    (key, value['version'], value['completions']),)

            if value['completions'] > value['starts']:
                yield ('Completions > starts: exp_id:%s version:%s %s>%s' % (
                    key, value['version'], value['completions'],
                    value['starts']),)

            if value['version'] == stats_jobs_continuous.VERSION_ALL:
                all_starts = value['starts']
                all_completions = value['completions']
                for (state_name, counts) in value['state_hit'].iteritems():
                    all_state_hit[state_name] = counts['first_entry_count']
            else:
                sum_starts += value['starts']
                sum_completions += value['completions']
                for (state_name, counts) in value['state_hit'].iteritems():
                    sum_state_hit[state_name] += counts['first_entry_count']

        if sum_starts != all_starts:
            yield (
                'Non-all != all for starts: exp_id:%s sum: %s all: %s'
                % (key, sum_starts, all_starts),)
        if sum_completions != all_completions:
            yield (
                'Non-all != all for completions: exp_id:%s sum: %s all: %s'
                % (key, sum_completions, all_completions),)

        for state_name in all_state_hit:
            if (state_name not in sum_state_hit and
                    all_state_hit[state_name] != 0):
                yield (
                    'state hit count not same exp_id:%s state:%s, '
                    'all:%s sum: null' % (
                        key, state_name, all_state_hit[state_name]),)
            elif all_state_hit[state_name] != sum_state_hit[state_name]:
                yield (
                    'state hit count not same exp_id: %s state: %s '
                    'all: %s sum:%s' % (
                        key, state_name, all_state_hit[state_name],
                        sum_state_hit[state_name]),)


class AnswersAudit(jobs.BaseMapReduceJobManager):

    _STATE_COUNTER_ERROR_KEY = 'State Counter ERROR'
    _HANDLER_NAME_COUNTER_KEY = 'HandlerCounter'
    _HANDLER_FUZZY_RULE_COUNTER_KEY = 'FuzzyRuleCounter'
    _HANDLER_DEFAULT_RULE_COUNTER_KEY = 'DefaultRuleCounter'
    _HANDLER_STANDARD_RULE_COUNTER_KEY = 'StandardRuleCounter'
    _HANDLER_ERROR_RULE_COUNTER_KEY = 'ErrorRuleCounter'

    @classmethod
    def _get_consecutive_dot_count(cls, string, idx):
        for i in range(idx, len(string)):
            if string[i] != '.':
                return i - idx
        return 0

    @classmethod
    def entity_classes_to_map_over(cls):
        return [stats_models.StateRuleAnswerLogModel]

    @staticmethod
    def map(item):
        item_id = item.id
        period_idx = item_id.index('.')
        period_idx += (
            AnswersAudit._get_consecutive_dot_count(item_id, period_idx) - 1)
        # exp_id = item_id[:period_idx]

        item_id = item_id[period_idx+1:]
        period_idx = item_id.index('.')
        period_idx += (
            AnswersAudit._get_consecutive_dot_count(item_id, period_idx) - 1)
        # state_name = item_id[:period_idx]

        item_id = item_id[period_idx+1:]
        period_idx = item_id.index('.')
        period_idx += (
            AnswersAudit._get_consecutive_dot_count(item_id, period_idx) - 1)
        handler_name = item_id[:period_idx]
        yield (handler_name, {
            'reduce_type': AnswersAudit._HANDLER_NAME_COUNTER_KEY,
            'rule_spec_str': item.id
        })

        item_id = item_id[period_idx+1:]
        rule_str = item_id

        if rule_str == 'FuzzyMatches':
            yield (rule_str, {
                'reduce_type': AnswersAudit._HANDLER_FUZZY_RULE_COUNTER_KEY
            })
        elif rule_str == 'Default':
            yield (rule_str, {
                'reduce_type': AnswersAudit._HANDLER_DEFAULT_RULE_COUNTER_KEY
            })
        elif '(' in rule_str and rule_str[-1] == ')':
            index = rule_str.index('(')
            rule_type = rule_str[0:index]
            rule_args = rule_str[index+1:-1]
            yield (rule_type, {
                'reduce_type': AnswersAudit._HANDLER_STANDARD_RULE_COUNTER_KEY,
                'rule_str': rule_str,
                'rule_args': rule_args
            })
        else:
            yield (rule_str, {
                'reduce_type': AnswersAudit._HANDLER_ERROR_RULE_COUNTER_KEY
            })

    @staticmethod
    def reduce(key, stringified_values):
        reduce_type = None
        reduce_count = len(stringified_values)
        for value_str in stringified_values:
            value_dict = ast.literal_eval(value_str)
            if reduce_type and reduce_type != value_dict['reduce_type']:
                yield 'Internal error 1'
            elif not reduce_type:
                reduce_type = value_dict['reduce_type']

        if reduce_type == AnswersAudit._HANDLER_NAME_COUNTER_KEY:
            rule_spec_strs = []
            for value_str in stringified_values:
                value_dict = ast.literal_eval(value_str)
                rule_spec_strs.append(value_dict['rule_spec_str'])
            yield (
                'Found handler "%s" %d time(s), ALL RULE SPEC STRINGS: \n%s' % (
                    key, reduce_count, rule_spec_strs))
        elif reduce_type == AnswersAudit._HANDLER_FUZZY_RULE_COUNTER_KEY:
            yield 'Found fuzzy rules %d time(s)' % reduce_count
        elif reduce_type == AnswersAudit._HANDLER_DEFAULT_RULE_COUNTER_KEY:
            yield 'Found default rules %d time(s)' % reduce_count
        elif reduce_type == AnswersAudit._HANDLER_STANDARD_RULE_COUNTER_KEY:
            yield 'Found rule type "%s" %d time(s)' % (key, reduce_count)
        elif reduce_type == AnswersAudit._HANDLER_ERROR_RULE_COUNTER_KEY:
            yield (
                'Encountered invalid rule string %d time(s) (is it too long?): '
                '"%s"' % (reduce_count, key))
        else:
            yield 'Internal error 2'
