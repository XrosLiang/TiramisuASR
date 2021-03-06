# Copyright 2020 Huy Le Nguyen (@usimarit)
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

import os
import argparse
from tiramisu_asr.utils import setup_environment

setup_environment()
import tensorflow as tf

from tiramisu_asr.configs.user_config import UserConfig
from tiramisu_asr.datasets.asr_dataset import ASRTFRecordDataset, ASRSliceDataset
from tiramisu_asr.featurizers.speech_featurizers import TFSpeechFeaturizer
from tiramisu_asr.featurizers.text_featurizers import TextFeaturizer
from tiramisu_asr.runners.ctc_runners import CTCTrainer
from model import DeepSpeech2

DEFAULT_YAML = os.path.join(os.path.abspath(os.path.dirname(__file__)), "configs", "vivos.yml")


def main():
    tf.keras.backend.clear_session()

    parser = argparse.ArgumentParser(prog="Deep Speech 2 Training")

    parser.add_argument("--config", "-c", type=str, default=DEFAULT_YAML,
                        help="The file path of model configuration file")

    parser.add_argument("--export", "-e", type=str, default=None,
                        help="Path to the model file to be exported")

    parser.add_argument("--mixed_precision", type=bool, default=False,
                        help="Whether to use mixed precision training")

    parser.add_argument("--save_weights", type=bool, default=False,
                        help="Whether to save or load only weights")

    parser.add_argument("--max_ckpts", type=int, default=10,
                        help="Max number of checkpoints to keep")

    parser.add_argument("--eval_train_ratio", type=int, default=1,
                        help="ratio between train batch size and eval batch size")

    parser.add_argument("--tfrecords", type=bool, default=False,
                        help="Whether to use tfrecords dataset")

    args = parser.parse_args()

    config = UserConfig(DEFAULT_YAML, args.config, learning=True)
    speech_featurizer = TFSpeechFeaturizer(config["speech_config"])
    text_featurizer = TextFeaturizer(config["decoder_config"])

    tf.random.set_seed(2020)

    if args.mixed_precision:
        policy = tf.keras.mixed_precision.experimental.Policy("mixed_float16")
        tf.keras.mixed_precision.experimental.set_policy(policy)
        print("Enabled mixed precision training")

    if args.tfrecords:
        train_dataset = ASRTFRecordDataset(
            config["learning_config"]["dataset_config"]["train_paths"],
            config["learning_config"]["dataset_config"]["tfrecords_dir"],
            speech_featurizer, text_featurizer, "train",
            augmentations=config["learning_config"]["augmentations"], shuffle=True,
        )
        eval_dataset = ASRTFRecordDataset(
            config["learning_config"]["dataset_config"]["eval_paths"],
            config["learning_config"]["dataset_config"]["tfrecords_dir"],
            speech_featurizer, text_featurizer, "eval", shuffle=False
        )
    else:
        train_dataset = ASRSliceDataset(
            stage="train", speech_featurizer=speech_featurizer,
            text_featurizer=text_featurizer,
            data_paths=config["learning_config"]["dataset_config"]["eval_paths"],
            augmentations=config["learning_config"]["augmentations"], shuffle=True
        )
        eval_dataset = ASRSliceDataset(
            stage="train", speech_featurizer=speech_featurizer,
            text_featurizer=text_featurizer,
            data_paths=config["learning_config"]["dataset_config"]["eval_paths"],
            shuffle=True
        )

    ctc_trainer = CTCTrainer(speech_featurizer, text_featurizer,
                             config["learning_config"]["running_config"],
                             args.mixed_precision)
    # Build DS2 model
    f, c = speech_featurizer.compute_feature_dim()
    with ctc_trainer.strategy.scope():
        ds2_model = DeepSpeech2(input_shape=[None, f, c],
                                arch_config=config["model_config"],
                                num_classes=text_featurizer.num_classes,
                                name="deepspeech2")
        ds2_model._build([1, 50, f, c])
    # Compile
    ctc_trainer.compile(ds2_model, config["learning_config"]["optimizer_config"],
                        max_to_keep=args.max_ckpts)

    ctc_trainer.fit(train_dataset, eval_dataset, args.eval_train_ratio)

    if args.export:
        if args.save_weights:
            ctc_trainer.model.save_weights(args.export)
        else:
            ctc_trainer.model.save(args.export)


if __name__ == '__main__':
    main()
