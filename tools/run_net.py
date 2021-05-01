import csd.modeling.meta_arch
import csd.modeling.roi_heads
import detectron2.data
import detectron2.utils.comm as comm
import wandb
from csd.config import add_csd_config
from csd.engine import CSDTrainerManager
from detectron2.config import get_cfg, set_global_cfg
from detectron2.engine import default_argument_parser, default_setup, launch
from detectron2.evaluation import verify_results


def check_config(cfg):
    """Checks that provided configuration parameters are supported.

    Note:
        - for details on parameters,, see `csd.config.config.py`
        - many additional checks are performed in other files;
        - checks here are not extensive, but should be still helpful.
    """

    assert cfg.DATALOADER.ASPECT_RATIO_GROUPING is True
    assert cfg.DATALOADER.SAMPLER_TRAIN == "TrainingSampler"
    assert cfg.MODEL.PROPOSAL_GENERATOR.NAME == "RPN"
    assert cfg.MODEL.KEYPOINT_ON is False
    assert cfg.MODEL.LOAD_PROPOSALS is None


def setup(args):
    """Reads & merges configs and executes default detectron2's setup"""

    cfg = get_cfg()  # Load default config
    add_csd_config(cfg)  # Extend with CSD-specific config
    cfg.merge_from_file(args.config_file)  # Extend with config from specified file
    cfg.merge_from_list(args.opts)  # Extend with config specified in args

    assert (  # Sanity check
        cfg.SOLVER.IMS_PER_BATCH == cfg.SOLVER.IMS_PER_BATCH_LABELED + cfg.SOLVER.IMS_PER_BATCH_UNLABELED
    ), "Total number of images per batch must be equal to the sum of labeled and unlabeled images per batch"

    cfg.freeze()
    set_global_cfg(cfg)  # Not really useful in this project, but kept for compatibility

    default_setup(cfg, args)
    check_config(cfg)

    return cfg


def eval_mode(cfg):
    """Runs the evaluation-only loop."""

    if cfg.VIS_TEST:
        assert cfg.USE_WANDB is True, "Visualizations use Wandb, therefore, it must be enabled"

    trainer = CSDTrainerManager(cfg)
    trainer.resume_or_load(resume=False)
    res = trainer.test(cfg, trainer._trainer.model)
    if comm.is_main_process():
        verify_results(cfg, res)
    return res

    pass


def main(args):
    """Sets up config, instantiates trainer, and uses it to start the training loop"""

    cfg = setup(args)

    if comm.is_main_process() and cfg.USE_WANDB:
        # Set up wandb (for tracking visualizations)
        wandb.login()
        wandb.init(project=cfg.WANDB_PROJECT_NAME, config=cfg)
    else:
        assert cfg.VIS_PERIOD == 0, "Visualizations without Wandb are not supported"

    if args.eval_only:  # TODO: implement eval only mode
        return eval_mode(cfg)

    # Set up the Trainer. I extend DefaultTrainer for managing the training loop. Effectively it's
    # not a trainer itself - it merely wraps the training loop, controls hooks, loading/saving, etc.
    # The trainer that actually runs the forward and backward passes is `CSDTrainer` stored in
    # `DefaultTrainer._trainer` (see `DefaultTrainer.__init__()`).
    trainer = CSDTrainerManager(cfg)
    trainer.resume_or_load(resume=args.resume)

    return trainer.train()


if __name__ == "__main__":
    args = default_argument_parser().parse_args()

    print("Command Line Args:", args)
    launch(
        main,
        args.num_gpus,
        num_machines=args.num_machines,
        machine_rank=args.machine_rank,
        dist_url=args.dist_url,
        args=(args,),
    )
