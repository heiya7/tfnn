import pandas as pd
import numpy as np
import tfnn


class Network(object):
    def __init__(self, n_inputs, n_outputs, input_dtype, output_dtype, output_activator,
                 do_dropout, do_l2, seed=None):
        self.n_inputs = n_inputs
        self.n_outputs = n_outputs
        self.input_dtype = input_dtype
        self.output_dtype = output_dtype
        self.output_activator = output_activator
        if do_dropout and do_l2:
            raise ValueError('Cannot do dropout and l2 at once. Choose only one of them.')
        if do_dropout:
            self.reg = 'dropout'
        if do_l2:
            self.reg = 'l2'
        if (do_dropout is False) & (do_l2 is False):
            self.reg = None
        self.seed = seed

        with tfnn.name_scope('inputs'):
            self.data_placeholder = tfnn.placeholder(dtype=input_dtype, shape=[None, n_inputs], name='x_input')
            self.target_placeholder = tfnn.placeholder(dtype=output_dtype, shape=[None, n_outputs], name='y_input')
            if do_dropout:
                self.keep_prob_placeholder = tfnn.placeholder(dtype=tfnn.float32)
                tfnn.scalar_summary('dropout_keep_probability', self.keep_prob_placeholder)
            if do_l2:
                self.l2_placeholder = tfnn.placeholder(tfnn.float32)
                tfnn.scalar_summary('l2_lambda', self.l2_placeholder)
        self.layers_output = pd.Series([])
        self.layers_activated_output = pd.Series([])
        self.layers_dropped_output = pd.Series([])
        self.layers_final_output = pd.Series([])
        self.Ws = pd.Series([])
        self.bs = pd.Series([])
        self.record_activators = pd.Series([])
        self.record_neurons = []
        self.last_layer_neurons = n_inputs
        self.last_layer_outputs = self.data_placeholder
        self.hidden_layer_number = 1
        self.has_output_layer = False
        self._is_output_layer = False

    def add_hidden_layer(self, n_neurons, activator=None, dropout_layer=False):
        """
        W shape(n_last_layer_neurons, n_this_layer_neurons]
        b shape(n_this_layer_neurons, ]
        product = tfnn.matmul(x, W) + b
        :param n_neurons: Number of neurons in this layer
        :param activator: The activation function
        :return:
        """
        if not self._is_output_layer:
            layer_name = 'hidden_layer%i' % self.hidden_layer_number
        else:
            layer_name = 'output_layer'
        with tfnn.name_scope(layer_name):
            with tfnn.name_scope('weights'):
                W = self._weight_variable([self.last_layer_neurons, n_neurons])
                self._variable_summaries(W, layer_name+'/weights')
            with tfnn.name_scope('biases'):
                b = self._bias_variable([n_neurons, ])
                self._variable_summaries(b, layer_name + '/biases')
            with tfnn.name_scope('Wx_plus_b'):
                product = tfnn.add(tfnn.matmul(self.last_layer_outputs, W, name='Wx'), b, name='Wx_plus_b')
            if activator is None:
                activated_product = product
            else:
                activated_product = activator(product)
            tfnn.histogram_summary(layer_name+'/activated_product', activated_product)
            if (self.reg == 'dropout') and dropout_layer:
                dropped_product = tfnn.nn.dropout(activated_product,
                                                self.keep_prob_placeholder,
                                                seed=self.seed, name='dropout')
                self.layers_dropped_output.set_value(label=len(self.layers_dropped_output),
                                                     value=dropped_product)
                final_product = dropped_product
            else:
                final_product = activated_product

        self.hidden_layer_number += 1
        self.last_layer_outputs = final_product
        self.Ws.set_value(label=len(self.Ws), value=W)
        self.bs.set_value(label=len(self.bs), value=b)
        if activator is None:
            self.record_activators.set_value(label=len(self.record_activators), value=None)
        else:
            self.record_activators.set_value(label=len(self.record_activators), value=activator(0).name)
        self.record_neurons.append(n_neurons)

        self.layers_output.set_value(label=len(self.layers_output),
                                     value=product)
        self.layers_activated_output.set_value(label=len(self.layers_output),
                                               value=activated_product)
        self.layers_final_output.set_value(label=len(self.layers_final_output),
                                           value=final_product)
        self.last_layer_neurons = n_neurons

    def add_output_layer(self, activator, dropout_layer=False):
        self._is_output_layer = True
        self.add_hidden_layer(self.n_outputs, activator, dropout_layer)
        self._init_loss()
        self.has_output_layer = True

    def set_optimizer(self, optimizer=None, global_step=None,):
        if optimizer is None:
            optimizer = tfnn.train.GradientDescentOptimizer(0.001)
        if not self.has_output_layer:
            raise NotImplementedError('Please add output layer.')
        with tfnn.name_scope('trian'):
            self.train_op = optimizer.minimize(self.loss, global_step)
        self.sess = tfnn.Session()

    def run_step(self, feed_xs, feed_ys, *args):
        if np.ndim(feed_xs) == 1:
            feed_xs = feed_xs[np.newaxis, :]
        if np.ndim(feed_ys) == 1:
            feed_ys = feed_ys[np.newaxis, :]
        if not hasattr(self, '_init'):
            # initialize all variables
            self._init = tfnn.initialize_all_variables()
            self.sess.run(self._init)

        if self.reg == 'dropout':
            keep_prob = args[0]
            self.sess.run(self.train_op, feed_dict={self.data_placeholder: feed_xs,
                                                    self.target_placeholder: feed_ys,
                                                    self.keep_prob_placeholder: keep_prob})
        elif self.reg == 'l2':
            l2 = args[0]
            self.sess.run(self.train_op, feed_dict={self.data_placeholder: feed_xs,
                                                    self.target_placeholder: feed_ys,
                                                    self.l2_placeholder: l2})
        else:
            self.sess.run(self.train_op, feed_dict={self.data_placeholder: feed_xs,
                                                    self.target_placeholder: feed_ys})

    def get_loss(self, xs, ys):
        if self.reg == 'dropout':
            _loss_value = self.sess.run(self.loss, feed_dict={self.data_placeholder: xs,
                                                              self.target_placeholder: ys,
                                                              self.keep_prob_placeholder: 1.})
        elif self.reg == 'l2':
            _loss_value = self.sess.run(self.loss, feed_dict={self.data_placeholder: xs,
                                                              self.target_placeholder: ys,
                                                              self.l2_placeholder: 0})
        else:
            _loss_value = self.sess.run(self.loss, feed_dict={self.data_placeholder: xs,
                                                              self.target_placeholder: ys})
        return _loss_value

    def get_weights(self, layer=None):
        if not(layer is None or type(layer) is int):
            raise TypeError('layer need to be None or int')
        if layer is None:
            Ws = []
            for W_layer in self.Ws:
                W = self.sess.run(W_layer)
                Ws.append(W)
        else:
            if layer >= len(self.Ws):
                raise IndexError('Do not have layer %i' % layer)
            Ws = self.sess.run(self.Ws[layer])
        return Ws

    def predict(self, xs):
        if np.ndim(xs) == 1:
            xs = xs[np.newaxis, :]
        predictions = self.sess.run(self.predictions, feed_dict={self.data_placeholder: xs})
        if predictions.size == 1:
            predictions = predictions[0][0]
        return predictions

    def _weight_variable(self, shape):
        initial = tfnn.random_normal(
            shape, mean=0.0, stddev=0.2, dtype=self.input_dtype, seed=self.seed, name='weights')
        return tfnn.Variable(initial)

    def _bias_variable(self, shape):
        initial = tfnn.constant(0.1, shape=shape, dtype=self.input_dtype, name='biases')
        return tfnn.Variable(initial)

    @staticmethod
    def _variable_summaries(var, name):
        with tfnn.name_scope("summaries"):
            mean = tfnn.reduce_mean(var)
            tfnn.scalar_summary('mean/' + name, mean)
            with tfnn.name_scope('stddev'):
                stddev = tfnn.sqrt(tfnn.reduce_sum(tfnn.square(var - mean)))
            tfnn.scalar_summary('sttdev/' + name, stddev)
            tfnn.scalar_summary('max/' + name, tfnn.reduce_max(var))
            tfnn.scalar_summary('min/' + name, tfnn.reduce_min(var))
            tfnn.histogram_summary(name, var)

    def _init_loss(self):
        self.loss = None
