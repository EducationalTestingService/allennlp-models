from flaky import flaky
import numpy
from numpy.testing import assert_almost_equal

import pytest

from allennlp.common import Params
from allennlp.common.testing import ModelTestCase
from allennlp.data import DatasetReader, Vocabulary
from allennlp.data import Batch
from allennlp.models import Model

from allennlp_models import rc  # noqa: F401

from tests import FIXTURES_ROOT


class QaNetTest(ModelTestCase):
    def setup_method(self):
        super().setup_method()
        self.set_up_model(
            FIXTURES_ROOT / "rc" / "qanet" / "experiment.json", FIXTURES_ROOT / "rc" / "squad.json"
        )

    @flaky
    def test_forward_pass_runs_correctly(self):
        batch = Batch(self.instances)
        batch.index_instances(self.vocab)
        training_tensors = batch.as_tensor_dict()
        output_dict = self.model(**training_tensors)

        metrics = self.model.get_metrics(reset=True)
        # We've set up the data such that there's a fake answer that consists of the whole
        # paragraph.  _Any_ valid prediction for that question should produce an F1 of greater than
        # zero, while if we somehow haven't been able to load the evaluation data, or there was an
        # error with using the evaluation script, this will fail.  This makes sure that we've
        # loaded the evaluation data correctly and have hooked things up to the official evaluation
        # script.
        assert metrics["f1"] > 0

        span_start_probs = output_dict["span_start_probs"][0].data.numpy()
        span_end_probs = output_dict["span_start_probs"][0].data.numpy()
        assert_almost_equal(numpy.sum(span_start_probs, -1), 1, decimal=6)
        assert_almost_equal(numpy.sum(span_end_probs, -1), 1, decimal=6)
        span_start, span_end = tuple(output_dict["best_span"][0].data.numpy())
        assert span_start >= 0
        assert span_start <= span_end
        assert span_end < self.instances[0].fields["passage"].sequence_length()
        assert isinstance(output_dict["best_span_str"][0], str)

    @pytest.mark.skip(reason="This test no longer passes with pytorch 1.13.1.")
    def test_model_can_train_save_and_load(self):
        self.ensure_model_can_train_save_and_load(self.param_file, tolerance=1e-4)

    def test_batch_predictions_are_consistent(self):
        # The same issue as the bidaf test case.
        # The CNN encoder has problems with this kind of test - it's not properly masked yet, so
        # changing the amount of padding in the batch will result in small differences in the
        # output of the encoder. So, we'll remove the CNN encoder entirely from the model for this test.
        # Save some state.

        saved_model = self.model
        saved_instances = self.instances

        # Modify the state, run the test with modified state.
        params = Params.from_file(self.param_file)
        reader = DatasetReader.from_params(params["dataset_reader"])
        reader._token_indexers = {"tokens": reader._token_indexers["tokens"]}
        self.instances = list(reader.read(FIXTURES_ROOT / "rc" / "squad.json"))
        vocab = Vocabulary.from_instances(self.instances)
        for instance in self.instances:
            instance.index_fields(vocab)
        del params["model"]["text_field_embedder"]["token_embedders"]["token_characters"]
        params["model"]["phrase_layer"]["num_convs_per_block"] = 0
        params["model"]["modeling_layer"]["num_convs_per_block"] = 0
        self.model = Model.from_params(vocab=vocab, params=params["model"])

        self.ensure_batch_predictions_are_consistent()

        # Restore the state.
        self.model = saved_model
        self.instances = saved_instances
