"""
Predict
"""
from datetime import datetime
from tqdm import tqdm
import numpy as np
import random, os, sys, torch, cv2, warnings
from glob import glob
from torch.utils.data import DataLoader

prj_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(prj_dir)

from modules.utils import load_yaml, save_yaml, get_logger
from modules.scalers import get_image_scaler
from modules.datasets import SegDataset_TTA
from models.utils import get_model
warnings.filterwarnings('ignore')

if __name__ == '__main__':

    #! Load config
    config = load_yaml(os.path.join(prj_dir, 'config', 'predict.yaml'))
    train_config = load_yaml(os.path.join(prj_dir, 'results', 'train', config['train_serial'], 'train.yaml'))
    
    #! Set predict serial
    pred_serial = config['train_serial'] + '_' + datetime.now().strftime("%Y%m%d_%H%M%S")

    # Set random seed, deterministic
    torch.cuda.manual_seed(train_config['seed'])
    torch.manual_seed(train_config['seed'])
    np.random.seed(train_config['seed'])
    random.seed(train_config['seed'])
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False

    # Set device(GPU/CPU)
    os.environ['CUDA_VISIBLE_DEVICES'] = str(config['gpu_num'])
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    
    # Create train result directory and set logger
    pred_result_dir = os.path.join(prj_dir, 'results', 'pred', pred_serial)
    pred_result_dir_mask = os.path.join(prj_dir, 'results', 'pred', pred_serial, 'mask')
    os.makedirs(pred_result_dir, exist_ok=True)
    os.makedirs(pred_result_dir_mask, exist_ok=True)

    # Set logger
    logging_level = 'debug' if config['verbose'] else 'info'
    logger = get_logger(name='train',
                        file_path=os.path.join(pred_result_dir, 'pred.log'),
                        level=logging_level)

    # Set data directory
    test_dirs = os.path.join(prj_dir, 'data', 'test')
    test_img_paths = glob(os.path.join(test_dirs, 'x', '*.png'))

    #! Load data & create dataset for train 
    test_dataset = SegDataset_TTA(paths=test_img_paths,
                            input_size=[train_config['input_width'], train_config['input_height']],
                            scaler=get_image_scaler(train_config['scaler']),
                            mode='test',
                            logger=logger)

    # Create data loader
    test_dataloader = DataLoader(dataset=test_dataset,
                                batch_size=config['batch_size'],
                                num_workers=config['num_workers'],
                                shuffle=False,
                                drop_last=False)
    logger.info(f"Load test dataset: {len(test_dataset)}")

    # Load architecture
    model = get_model(model_str=train_config['architecture'])
    if train_config['architecture'] == 'Lawin':
        model.to(device)
    else:
        model = model(
                    classes=train_config['n_classes'],
                    encoder_name=train_config['encoder'],
                    encoder_weights=train_config['encoder_weight'],
                    activation=train_config['activation']).to(device)
    logger.info(f"Load model architecture: {train_config['architecture']}")

    #! Load weight
    check_point_path = os.path.join(prj_dir, 'results', 'train', config['train_serial'], 'model.pt')
    check_point = torch.load(check_point_path)
    model.load_state_dict(check_point['model'])
    logger.info(f"Load model weight, {check_point_path}")

    # Save config
    save_yaml(os.path.join(pred_result_dir, 'train_config.yml'), train_config)
    save_yaml(os.path.join(pred_result_dir, 'predict_config.yml'), config)
    
    # Predict
    logger.info(f"START PREDICTION")

    model.eval()

    with torch.no_grad():

        for batch_id, (x, x2, x3, x4, orig_size, filename) in enumerate(tqdm(test_dataloader)):
            
            x = x.to(device, dtype=torch.float)
            x2 = x2.to(device, dtype=torch.float)
            x3 = x3.to(device, dtype=torch.float)
            x4 = x4.to(device, dtype=torch.float)

            y_pred = model(x)
            y_pred2 = model(x2)
            y_pred3 = model(x3)
            y_pred4 = model(x4)

            y_pred = y_pred.cpu().numpy()
            y_pred2 = y_pred2.cpu().numpy()
            y_pred3 = y_pred3.cpu().numpy()
            y_pred4 = y_pred4.cpu().numpy()

            for i in range(y_pred.shape[0]):
                for x in range(4):
                    im1 = y_pred2[i][x][:, :224]
                    im2 = y_pred2[i][x][:, 224:]
                    im1 = np.rot90(im1, 1)
                    im2 = np.rot90(im2, 1)
                    y_pred2[i][x] = cv2.hconcat([im1, im2])

                    im1 = y_pred3[i][x][:, :224]
                    im2 = y_pred3[i][x][:, 224:]
                    im1 = np.rot90(im1, 2)
                    im2 = np.rot90(im2, 2)
                    y_pred3[i][x] = cv2.hconcat([im1, im2])

                    im1 = y_pred4[i][x][:, :224]
                    im2 = y_pred4[i][x][:, 224:]
                    im1 = np.rot90(im1, 3)
                    im2 = np.rot90(im2, 3)
                    y_pred4[i][x] = cv2.hconcat([im1, im2])

            y_pred += y_pred2
            y_pred += y_pred3
            y_pred += y_pred4

            y_pred_argmax = np.argmax(y_pred, axis=1).astype(np.uint8)
            
            orig_size = [(orig_size[0].tolist()[i], orig_size[1].tolist()[i]) for i in range(len(orig_size[0]))]
            # Save predict result
            for filename_, orig_size_, y_pred_ in zip(filename, orig_size, y_pred_argmax):
                resized_img = cv2.resize(y_pred_, [orig_size_[1], orig_size_[0]], interpolation=cv2.INTER_NEAREST)
                cv2.imwrite(os.path.join(pred_result_dir_mask, filename_), resized_img)
                
    logger.info(f"END PREDICTION")