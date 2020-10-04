from bittensor import bittensor_pb2
import bittensor

import os, sys
import argparse
import math
import time

import torch
from torch import nn
import torch.nn.functional as F
from typing import List, Tuple, Dict, Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

import transformers
from datasets import load_dataset, list_metrics, load_metric
from transformers import DataCollatorForNextSentencePrediction
from transformers import BertTokenizer

class BertNSPSynapse(bittensor.Synapse):
    """ An bittensor endpoint trained on wiki corpus.
    """
    def __init__(self):
        super(BertNSPSynapse, self).__init__()                
        self.config = transformers.modeling_bert.BertConfig(hidden_size=256, num_hidden_layers=2, num_attention_heads=2, intermediate_size=512, is_decoder=False)
        
        self.tokenizer = BertTokenizer.from_pretrained('bert-base-uncased')

        self.embeddings = transformers.modeling_bert.BertEmbeddings(self.config)

        self.encoder = transformers.modeling_bert.BertEncoder(self.config)

        self.pooler = transformers.modeling_bert.BertPooler(self.config)

        self.student_encoder = transformers.modeling_bert.BertEncoder(self.config)

        self.student_pooler = transformers.modeling_bert.BertPooler(self.config)

        self.nsp = transformers.modeling_bert.BertOnlyNSPHead(self.config) 

        self.nsp_loss_fct = torch.nn.CrossEntropyLoss()

    def forward_text(self, inputs: List[str]):
        return self.forward(inputs = inputs, next_inputs = None, labels = None, network = None) ['local_output']
        
    def forward(    self, 
                    inputs: List[str], 
                    next_inputs: List[str] = None, 
                    labels: torch.Tensor = None, 
                    network: torch.Tensor = None):

        # Return args.
        loss = torch.tensor(0.0)
        local_output = None
        network_output = None
        network_target_loss = None
        local_target_loss = None
        distillation_loss = None
                    
        # Tokenize inputs: dict
        #  tokenized = dict {
        #       'input_ids': torch.Tensor(batch_size, max_sequence_len),
        #       'token_type_ids': torch.Tensor(batch_size, max_sequence_len),
        #       'attention_mask': torch.Tensor(batch_size, max_sequence_len)
        # }
        if labels is not None:
            # During training we tokenize both sequences and return token_type_ids which tell
            # the model which token belongs to which sequence.
            # i.e tensor([[0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1]]),
            tokenized = self.tokenizer(inputs, next_inputs, return_tensors='pt', padding=True)
        else:
            # During inference we only tokenize the inputs, padding them to the longest sequence len.
            tokenized = self.tokenizer(inputs, return_tensors='pt', padding=True)

        # Embed tokens into a common dimension.
        # embedding = torch.Tensor(batch_size, max_sequence_len, config.hidden_size)
        embedding = self.embeddings(input_ids=tokenized['input_ids'], token_type_ids=tokenized['token_type_ids'])

        # Bert transformer encodings returning the last hidden states from the transformer model.
        # encoding = List [
        #   hidden_states = torch.Tensor(batch_size, max_sequence_len, config.hidden_size), 
        # ]
        encoding = self.encoder(embedding)

        # Pooling, "pool" the model by simply taking the hidden state corresponding
        # to the first token. first_token_tensor = encoding[:, 0]. Applies a dense linear
        # layer to the encoding for the first token. 
        # pooled = torch.Tensor (batch_size, config.hidden_size)
        pooled = self.pooler(encoding[0])

        # Student transformer model which learns a mapping from the embedding to the network inputs
        # student_pooled = torch.Tensor (batch_size, config.hidden_size)
        student_encoding = self.student_encoder (embedding.detach())
        student_pooled = self.student_pooler(student_encoding[0])
        if network is not None:
            # Distillation loss between student_pooled and network inputs.
            distillation_loss = F.mse_loss(student_pooled, network) 
            loss += distillation_loss

        # Output from the forward pass using only the local and student models.
        # local_ouput = torch.Tensor ( batch_size, config.hidden_size)
        local_output = pooled + student_pooled
        if labels is not None:
            # Compute the NSP loss by projecting the output to torch.Tensor(2)
            # logit(1) > logit(0) if next_inputs are the real next sequences.
            local_prediction = self.nsp(local_output)
            local_target_loss = self.nsp_loss_fct(local_prediction.view(-1, 2), labels)
            loss += local_target_loss
            
        # Compute NSP loss for network outputs. Only run this if we have passed network inputs.
        if network is not None and labels is not None:
            # Compute the NSP loss by projecting the network_output to torch.Tensor(2)
            # logit(1) > logit(0) if next_inputs are the real next sequences.
            network_output = pooled + network
            network_prediction = self.nsp(network_output)
            network_target_loss = self.nsp_loss_fct(network_prediction.view(-1, 2), labels)
            loss += network_target_loss
    
        return {
            'loss': loss,
            'local_output': local_output,
            'network_output': network_output,
            'network_target_loss': network_target_loss,
            'student_target_loss': local_target_loss,
            'distillation_loss': distillation_loss
        }
            
def main(hparams):
    # Args
    config = bittensor.Config( hparams )
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Dataset
    dataset = load_dataset('bookcorpus')

    # Build Synapse
    model = BertNSPSynapse()
    model.to(device)

    # Build and start the metagraph background object.
    # The metagraph is responsible for connecting to the blockchain
    # and finding the other neurons on the network.
    metagraph = bittensor.Metagraph( config )
    metagraph.subscribe( model ) # Adds the synapse to the metagraph.
    metagraph.start() # Starts the metagraph gossip threads.
    
    # Build and start the Axon server.
    # The axon server serves the synapse objects 
    # allowing other neurons to make queries through a dendrite.
    axon = bittensor.Axon( config )
    axon.serve( model ) # Makes the synapse available on the axon server.
    axon.start() # Starts the server background threads. Must be paired with axon.stop().
    
    # Build the dendrite and router. 
    # The dendrite is a torch object which makes calls to synapses across the network
    # The router is responsible for learning which synapses to call.
    dendrite = bittensor.Dendrite( config )
    router = bittensor.Router(x_dim = 256, key_dim = 100, topk = 10)
    
    # Optimizer.
    lr = 3.0 # learning rate
    params = list(router.parameters()) + list(model.parameters())
    optimizer = torch.optim.SGD(params, lr=lr)
    
    def train(dataset, transformer, epoch):
        model.train()  # Turn on the train mode.
        optimizer.zero_grad() # Zero out lingering gradients.

        batch_size = 10
        inputs = dataset['train'][0: batch_size]['text']
        next_inputs = dataset['train'][1: batch_size+1]['text']
        labels = torch.ones(batch_size, dtype=torch.long)
        
        # Get routing context
        context = model.forward_text( inputs )
        
        # Query the remote network.
        # Flatten mnist inputs for routing.
        synapses = metagraph.get_synapses( 1000 ) # Returns a list of synapses on the network (max 1000).
        requests, scores = router.route( synapses, context, inputs ) # routes inputs to network.
        responses = dendrite.forward_text( synapses, requests ) # Makes network calls.
        network = router.join( responses ) # Joins responses based on scores..
        
        # Compute full pass and get loss.
        output = model.forward(inputs, next_inputs, labels, network)
        
        loss = output['loss']
        loss.backward()
        optimizer.step()

        logger.info("loss {}", loss.item())
          
        # Set network weights.
        weights = metagraph.getweights(synapses).to(model.device)
        weights = (0.99) * weights + 0.01 * torch.mean(scores, dim=0)
        metagraph.setweights(synapses, weights)
      
    epoch = 0
    try:
        while True:
            train(dataset, model, epoch)
            epoch += 1
    except Exception as e:
        logger.exception(e)
        metagraph.stop()
        axon.stop()
        


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    hparams = bittensor.Config.add_args(parser)
    hparams = parser.parse_args()
    main(hparams)