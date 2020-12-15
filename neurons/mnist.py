"""Training a MNIST Neuron.
This file demonstrates a training pipeline for an MNIST Neuron.
Example:
        $ python neurons/mnist.py
"""
import argparse
import math
import os
import time
import torch
from termcolor import colored
import torch.nn.functional as F
import torch.optim as optim
import torchvision
import torchvision.transforms as transforms
from torch.utils.tensorboard import SummaryWriter

from munch import Munch
from loguru import logger

import bittensor
from bittensor import Session
from bittensor.utils.logging import log_all
from bittensor.subtensor import Keypair
from bittensor.config import Config
from bittensor.synapse import Synapse
from bittensor.synapses.ffnn import FFNNSynapse

def add_args(parser: argparse.ArgumentParser):    
    parser.add_argument('--neuron.datapath', default='data/', type=str,  help='Path to load and save data.')
    parser.add_argument('--neuron.learning_rate', default=0.01, type=float, help='Training initial learning rate.')
    parser.add_argument('--neuron.momentum', default=0.9, type=float, help='Training initial momentum for SGD.')
    parser.add_argument('--neuron.batch_size_train', default=64, type=int, help='Training batch size.')
    parser.add_argument('--neuron.batch_size_test', default=64, type=int, help='Testing batch size.')
    parser.add_argument('--neuron.log_interval', default=150, type=int, help='Batches until neuron prints log statements.')
    parser.add_argument('--neuron.sync_interval', default=150, type=int, help='Batches before we we sync with chain and emit new weights.')
    parser.add_argument('--neuron.name', default='mnist', type=str, help='Trials for this neuron go in neuron.datapath / neuron.name')
    parser.add_argument('--neuron.trial_id', default=str(time.time()).split('.')[0], type=str, help='Saved models go in neuron.datapath / neuron.name / neuron.trial_id')
    FFNNSynapse.add_args(parser)

def check_config(config: Munch):
    assert config.neuron.log_interval > 0, "log_interval dimension must positive"
    assert config.neuron.momentum > 0 and config.neuron.momentum < 1, "momentum must be a value between 0 and 1"
    assert config.neuron.batch_size_train > 0, "batch_size_train must a positive value"
    assert config.neuron.batch_size_test > 0, "batch_size_test must a positive value"
    assert config.neuron.learning_rate > 0, "learning rate must be a positive value."
<<<<<<< HEAD
    trial_path = '{}/{}/{}'.format(config.neuron.datapath, config.neuron.name, config.neuron.trial_id)
    config.neuron.trial_path = trial_path
    if not os.path.exists(config.neuron.trial_path):
        os.makedirs(config.neuron.trial_path)
    FFNNSynapse.check_config(config)
=======
    Config.validate_path_create('neuron.datapath', config.neuron.datapath)
    config = FFNNSynapse.check_config(config)
    return config

def train(
    epoch: int,
    model: Synapse,
    session: Session,
    config: Munch,
    optimizer: optim.Optimizer,
    trainloader: torch.utils.data.DataLoader):

    model.train() # Turn on Dropoutlayers BatchNorm etc.
    weights = None
    history = []
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    for batch_idx, (images, targets) in enumerate(trainloader):
        optimizer.zero_grad() # Clear gradients.

        # Syncs chain state and emits learned weights to the chain.
        if batch_idx % config.neuron.sync_interval == 0:
            weights = session.metagraph.sync(weights)
            weights = weights.to(device)

        # Sets the axon server priority.
        # Queries on this axon endpoint are processed from highest to lowest priority.
        if batch_idx % config.neuron.priority_interval == 0:
            weights_to_me = session.metagraph.W[:, 0]
            priority = dict(zip(session.metagraph.public_keys, weights_to_me.tolist()))
            session.axon.set_priority( priority )
     
        # Forward pass.
        output = model(images.to(model.device), torch.LongTensor(targets).to(model.device), remote = True)
        history.append(output)

        # Backprop.
        loss = output.remote_target_loss + output.distillation_loss
        loss.backward()
        optimizer.step()

        # Update weights.
        batch_weights = F.softmax(torch.mean(output.weights, axis=0), dim=0).to(device)
        weights = (1 - 0.05) * weights + 0.05 * batch_weights
        weights = weights / torch.sum(weights)

        # Logs:
        if (batch_idx + 1) % config.neuron.log_interval == 0: 
            total_examples = len(trainloader) * config.neuron.batch_size_train
            processed = ((batch_idx + 1) * config.neuron.batch_size_train)
            progress = (100. * processed) / total_examples
            logger.info('Epoch: {} [{}/{} ({})]', 
                        colored('{}'.format(epoch), 'blue'), 
                        colored('{}'.format(processed), 'green'), 
                        colored('{}'.format(total_examples), 'red'),
                        colored('{:.2f}%'.format(progress), 'green'))
            log_outputs(history)
            log_batch_weights(session, history)
            log_chain_weights(session)
            log_request_sizes(session, history)
            history = []

def test ( 
    model: Synapse,
    session: Session,
    testloader: torch.utils.data.DataLoader,
    num_tests: int):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.eval() # Turns off Dropoutlayers, BatchNorm etc.
    with torch.no_grad(): # Turns off gradient computation for inference speed up.
        loss = 0.0
        correct = 0.0
        for _, (images, labels) in enumerate(testloader):                
            # Compute full pass and get loss.
            images = images.to(model.device)
            labels =  torch.LongTensor(labels).to(model.device)
            outputs = model.forward(images, labels, remote = False)
            loss = loss + outputs.loss
            
            # Count accurate predictions.
            max_logit = outputs.local_target.data.max(1, keepdim=True)[1].to(model.device)
            correct = correct + max_logit.eq( labels.data.view_as(max_logit) ).sum()
    
    # Log results.
    n = num_tests * config.neuron.batch_size_test
    loss /= n
    accuracy = (100. * correct) / n
    logger.info('Test set: Avg. loss: {:.4f}, Accuracy: {}/{} ({:.0f}%)\n'.format(loss, correct, num_tests, accuracy))  
    session.tbwriter.write_loss('test loss', loss)
    session.tbwriter.write_accuracy('test accuracy', accuracy)
    return loss, accuracy
>>>>>>> a3299a9fd9cc98447887cc7d3c198d69b93cbd5c

# --- Train epoch ----
def main(config: Munch, session: Session):
    # ---- Model ----
    model = FFNNSynapse(config, session) # Feedforward neural network with PKMDendrite.
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to( device ) # Set model to device
    
    # ---- Serve ----
    session.serve( model ) # Serves model to Axon RPC endpoint for network access.

    # ---- Optimizer ---- 
    optimizer = optim.SGD(model.parameters(), lr=config.neuron.learning_rate, momentum=config.neuron.momentum)
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=10.0, gamma=0.1)

    # ---- Dataset ----
    train_data = torchvision.datasets.MNIST(root = config.neuron.datapath + "datasets/", train=True, download=True, transform=transforms.ToTensor())
    trainloader = torch.utils.data.DataLoader(train_data, batch_size = config.neuron.batch_size_train, shuffle=True, num_workers=2)
    test_data = torchvision.datasets.MNIST(root = config.neuron.datapath + "datasets/", train=False, download=True, transform=transforms.ToTensor())
    testloader = torch.utils.data.DataLoader(test_data, batch_size = config.neuron.batch_size_test, shuffle=False, num_workers=2)

    # ---- Tensorboard ----
    global_step = 0
    tensorboard = SummaryWriter(log_dir = config.neuron.trial_path)

    # --- Test epoch ----
    def test ():
        model.eval() # Turns off Dropoutlayers, BatchNorm etc.
        with torch.no_grad(): # Turns off gradient computation for inference speed up.
            loss = 0.0; accuracy = 0.0
            for _, (images, labels) in enumerate(testloader):                
                # ---- Forward pass ----
                outputs = model.forward(
                    images = images.to(model.device), 
                    targets = torch.LongTensor(labels).to(model.device), 
                    remote = False # *without* rpc-queries being made.
                )
                loss = loss + outputs.loss / len(test_data)
                accuracy = outputs['local_accuracy'] / len(test_data)
        return loss, accuracy

    # ---- Train epoch ----
    def train(epoch: int, global_step: int):

        # ---- Init training state ----
        model.train() # Turn on dropout etc.
        session.metagraph.sync() # Sync with the chain.
        row_weights = session.metagraph.W[ 0, :] # My weights on the chain-state (zeros initially).

        history = []
        for batch_idx, (images, targets) in enumerate(trainloader):     

            # ---- Forward pass ----
            output = model(  
                images = images.to(model.device), 
                targets = torch.LongTensor(targets).to(model.device), 
                remote = True # *with* rpc-queries made to the network.
            ) 
            
            # ---- Backward pass ----
            output.loss.backward() # Accumulates gradients on the model.
            optimizer.step() # Applies accumulated gradients.
            optimizer.zero_grad() # Zeros out gradients for next accummulation 

            # ---- Serve Model ----
            session.serve( model ) # Serve the newest model.

            # ---- Update State ----
            batch_weights = torch.mean(output.weights, axis = 0) # Average over batch.
            row_weights = (1 - 0.03) * row_weights + 0.03 * batch_weights # Moving avg update.
            row_weights = F.normalize(row_weights, p = 1, dim = 0) # Ensure normalization.

            if (batch_idx+1) % config.neuron.sync_interval == 0:
                # ---- Sync Metagraph State ----
                logger.info('Emitting with weights {}', row_weights.tolist())
                session.metagraph.emit( row_weights ) # Sets my row-weights on the chain.
                session.metagraph.sync() # Pulls the latest metagraph state (with my update.)
                row_weights = session.metagraph.W[ 0, :] 
                
                # ---- Update Axon Priority ----
                col_weights = session.metagraph.W[:,0] # weights to me.
                session.axon.set_priority( session.metagraph.neurons, col_weights ) # Sets the nucleus-backend request priority.

            # ---- Step Logs + Tensorboard ----
            history.append(output) # Save for later analysis/logs.
            processed = ((batch_idx + 1) * config.neuron.batch_size_train)
            progress = (100. * processed) / len(train_data)
            logger.info('GS: {} Epoch: {} [{}/{} ({})]\t Loss: {}\t Acc: {}', 
                    colored('{}'.format(global_step), 'blue'), 
                    colored('{}'.format(epoch), 'blue'), 
                    colored('{}'.format(processed), 'green'), 
                    colored('{}'.format(len(train_data)), 'red'),
                    colored('{:.2f}%'.format(progress), 'green'),
                    colored('{:.4f}'.format(output.local_target_loss.item()), 'green'),
                    colored('{:.4f}'.format(output.metadata['local_accuracy'].item()), 'green'))
            tensorboard.add_scalar('Rloss', output.remote_target_loss.item(), global_step)
            tensorboard.add_scalar('Lloss', output.local_target_loss.item(), global_step)
            tensorboard.add_scalar('Dloss', output.distillation_loss.item(), global_step)
            if (batch_idx+1) % config.neuron.log_interval == 0:
                log_all(session, history); history = [] # Log batch history.

    # ---- Loop forever ----
    epoch = -1; best_test_loss = math.inf
    while True:
<<<<<<< HEAD
        epoch += 1

        # ---- Train model ----
        train(epoch, global_step)
        scheduler.step()
        
        # ---- Test model ----
        test_loss, test_accuracy = test()
=======
        # Train model
        train( 
            epoch = epoch,
            model = model,
            session = session,
            config = config,
            optimizer = optimizer,
            trainloader = trainloader
        )
        scheduler.step()

        # Test model.
        test_loss, test_accuracy = test( 
            model = model,
            session = session,
            testloader = testloader,
            num_tests = len(test_data),
        )
>>>>>>> a3299a9fd9cc98447887cc7d3c198d69b93cbd5c

         # ---- Save Best ----
        if test_loss < best_test_loss:
            best_test_loss = test_loss # Update best loss.
            logger.info( 'Saving/Serving model: epoch: {}, accuracy: {}, loss: {}, path: {}/model.torch'.format(epoch, test_accuracy, best_test_loss, config.neuron.trial_path))
            torch.save( {'epoch': epoch, 'model': model.state_dict(), 'loss': best_test_loss},"{}/model.torch".format(config.neuron.trial_path))
            tensorboard.add_scalar('Test loss', test_loss, global_step)

        
if __name__ == "__main__":
    # ---- Load config ----
    parser = argparse.ArgumentParser()
    add_args(parser)
    config = Config.load(parser)
    check_config(config)
    logger.info(Config.toString(config))

    # ---- Load Keypair ----
    mnemonic = Keypair.generate_mnemonic()
    keypair = Keypair.create_from_mnemonic(mnemonic)
   
    # ---- Build Session ----
    session = bittensor.init(config, keypair)

    # ---- Start Neuron ----
    with session:
        main(config, session)

